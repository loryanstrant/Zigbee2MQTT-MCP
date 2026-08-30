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


async def test_set_state_timeout_does_not_leak_a_waiter():
    """A device that never reports back must not leave its future behind."""
    c = make_client()  # request_timeout=1
    c._ws = FakeWS()
    c._connected.set()

    # No matching state update arrives, so the wait times out and we fall back
    # to the cached state.
    assert await c.set_state("Lamp", {"state": "ON"}) == {}
    assert c._state_waiters == {}


async def test_set_state_resolved_waiter_is_not_retained():
    c = make_client()
    c._ws = FakeWS()
    c._connected.set()
    task = asyncio.create_task(c.set_state("Lamp", {"state": "ON"}))
    await asyncio.sleep(0)
    c._handle(json.dumps({"topic": "Lamp", "payload": {"state": "ON"}}))
    await task
    assert c._state_waiters == {}


async def test_set_state_send_failure_does_not_leak_a_waiter():
    c = make_client()  # never connected, so _send raises
    with pytest.raises(Z2MError):
        await c.set_state("Lamp", {"state": "ON"})
    assert c._state_waiters == {}


def test_unknown_topics_are_not_cached_once_primed():
    c = make_client()
    c._handle(json.dumps({
        "topic": "bridge/devices", "payload": [{"friendly_name": "Lamp"}],
    }))

    c._handle(json.dumps({"topic": "Lamp", "payload": {"state": "ON"}}))
    c._handle(json.dumps({"topic": "Ghost", "payload": {"state": "ON"}}))
    c._handle(json.dumps({"topic": "Ghost/availability", "payload": "online"}))

    assert "Lamp" in c.device_state
    assert "Ghost" not in c.device_state
    assert "Ghost" not in c.availability


def test_group_names_count_as_known():
    c = make_client()
    c._handle(json.dumps({"topic": "bridge/devices", "payload": [{"friendly_name": "Lamp"}]}))
    c._handle(json.dumps({"topic": "bridge/groups", "payload": [{"friendly_name": "Kitchen"}]}))
    c._handle(json.dumps({"topic": "Kitchen", "payload": {"state": "ON"}}))
    assert c.device_state["Kitchen"] == {"state": "ON"}


def test_caches_pruned_when_a_device_disappears():
    c = make_client()
    c._handle(json.dumps({
        "topic": "bridge/devices",
        "payload": [{"friendly_name": "Lamp"}, {"friendly_name": "Old Sensor"}],
    }))
    c._handle(json.dumps({"topic": "Old Sensor", "payload": {"battery": 10}}))
    c._handle(json.dumps({"topic": "Old Sensor/availability", "payload": "offline"}))
    assert "Old Sensor" in c.device_state

    # Device removed or renamed — a fresh roster arrives without it.
    c._handle(json.dumps({"topic": "bridge/devices", "payload": [{"friendly_name": "Lamp"}]}))
    assert "Old Sensor" not in c.device_state
    assert "Old Sensor" not in c.availability


def test_empty_roster_does_not_wipe_the_caches():
    """A malformed/empty snapshot is not evidence that every device is gone."""
    c = make_client()
    c._handle(json.dumps({"topic": "bridge/devices", "payload": [{"friendly_name": "Lamp"}]}))
    c._handle(json.dumps({"topic": "Lamp", "payload": {"state": "ON"}}))
    c._handle(json.dumps({"topic": "bridge/devices", "payload": []}))
    assert c.device_state["Lamp"] == {"state": "ON"}


def test_state_arriving_before_the_roster_is_kept():
    """The retained snapshot replays in no guaranteed order."""
    c = make_client()
    c._handle(json.dumps({"topic": "Lamp", "payload": {"state": "ON"}}))
    c._handle(json.dumps({"topic": "bridge/devices", "payload": [{"friendly_name": "Lamp"}]}))
    assert c.device_state["Lamp"] == {"state": "ON"}
