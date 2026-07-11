import asyncio
import json

import pytest

from zigbee2mqtt_mcp.client import Z2MClient, Z2MError, Z2MNotReady
from zigbee2mqtt_mcp.settings import Settings


class FakeWS:
    """Minimal stand-in for a websockets connection that records sends."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    async def close(self) -> None:
        pass


def make_client(**env) -> Z2MClient:
    return Z2MClient(Settings(Z2M_REQUEST_TIMEOUT=1, **env))


def test_handle_routes_snapshot_and_primes():
    c = make_client()
    assert not c.primed
    c._handle(json.dumps({"topic": "bridge/devices", "payload": [{"friendly_name": "Lamp"}]}))
    assert c.primed
    assert c.devices == [{"friendly_name": "Lamp"}]

    c._handle(json.dumps({"topic": "bridge/info", "payload": {"version": "1.x"}}))
    assert c.bridge_info["version"] == "1.x"

    c._handle(json.dumps({"topic": "Lamp", "payload": {"state": "ON"}}))
    assert c.device_state["Lamp"] == {"state": "ON"}

    c._handle(json.dumps({"topic": "Lamp/availability", "payload": {"state": "online"}}))
    assert c.availability["Lamp"] == {"state": "online"}


def test_handle_ignores_garbage():
    c = make_client()
    c._handle("not json")  # must not raise
    c._handle(json.dumps(["not", "a", "dict"]))
    c._handle(json.dumps({"payload": {}}))  # no topic
    assert not c.primed


def test_find_device_requires_snapshot():
    c = make_client()
    with pytest.raises(Z2MNotReady):
        c.find_device("Lamp")


def test_find_device_by_name_and_ieee():
    c = make_client()
    c._handle(json.dumps({
        "topic": "bridge/devices",
        "payload": [{"friendly_name": "Lamp", "ieee_address": "0xABC"}],
    }))
    assert c.find_device("lamp")["ieee_address"] == "0xABC"
    assert c.find_device("0xabc")["friendly_name"] == "Lamp"
    assert c.find_device("nope") is None


async def test_request_correlates_response():
    c = make_client()
    c._ws = FakeWS()
    c._connected.set()

    task = asyncio.create_task(c.request("permit_join", {"value": True}))
    await asyncio.sleep(0)  # let the send happen

    sent = c._ws.sent[0]
    assert sent["topic"] == "bridge/request/permit_join"
    txn = sent["payload"]["transaction"]
    assert sent["payload"]["value"] is True

    # simulate Zigbee2MQTT's response
    c._handle(json.dumps({
        "topic": "bridge/response/permit_join",
        "payload": {"transaction": txn, "status": "ok", "data": {"value": True}},
    }))
    result = await task
    assert result["data"] == {"value": True}


async def test_request_error_status_raises():
    c = make_client()
    c._ws = FakeWS()
    c._connected.set()
    task = asyncio.create_task(c.request("device/remove", {"id": "X"}))
    await asyncio.sleep(0)
    txn = c._ws.sent[0]["payload"]["transaction"]
    c._handle(json.dumps({
        "topic": "bridge/response/device/remove",
        "payload": {"transaction": txn, "status": "error", "error": "device not found"},
    }))
    with pytest.raises(Z2MError, match="device not found"):
        await task


async def test_request_times_out():
    c = make_client()  # request_timeout=1
    c._ws = FakeWS()
    c._connected.set()
    with pytest.raises(Z2MError, match="Timed out"):
        await c.request("networkmap", {})


async def test_set_state_returns_next_update():
    c = make_client()
    c._ws = FakeWS()
    c._connected.set()
    task = asyncio.create_task(c.set_state("Lamp", {"state": "ON"}))
    await asyncio.sleep(0)
    assert c._ws.sent[0] == {"topic": "Lamp/set", "payload": {"state": "ON"}}
    c._handle(json.dumps({"topic": "Lamp", "payload": {"state": "ON", "brightness": 254}}))
    result = await task
    assert result == {"state": "ON", "brightness": 254}


async def test_send_without_connection_raises():
    c = make_client()  # never connected
    with pytest.raises(Z2MError, match="Not connected"):
        await c._send("Lamp/set", {"state": "ON"})
