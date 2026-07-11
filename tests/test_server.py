import json

import pytest

import zigbee2mqtt_mcp.server as server
from zigbee2mqtt_mcp.client import Z2MError


@pytest.fixture(autouse=True)
def primed_client(monkeypatch):
    """Prime the module client with a small device roster for each test."""
    c = server.client
    c.devices = []
    c._primed.clear()
    c._handle(json.dumps({
        "topic": "bridge/devices",
        "payload": [
            {"type": "Coordinator", "friendly_name": "Coordinator", "ieee_address": "0x0"},
            {
                "type": "EndDevice",
                "friendly_name": "RGB Downlight",
                "ieee_address": "0xAAA",
                "definition": {
                    "model": "LED1",
                    "vendor": "IKEA",
                    "description": "Bulb",
                    "exposes": [
                        {"features": [{"property": "state"}, {"property": "brightness"}]},
                        {"property": "linkquality"},
                    ],
                },
            },
        ],
    }))
    c._handle(json.dumps({"topic": "RGB Downlight", "payload": {"state": "OFF"}}))
    return c


def test_exposes_summary_flattens_features():
    definition = {
        "exposes": [
            {"features": [{"property": "state"}, {"name": "brightness"}]},
            {"property": "linkquality"},
            {"property": "state"},  # duplicate dropped
        ]
    }
    assert server._exposes_summary(definition) == ["state", "brightness", "linkquality"]


def test_list_devices_excludes_coordinator_by_default():
    result = server.list_devices()
    names = [d["friendly_name"] for d in result["devices"]]
    assert names == ["RGB Downlight"]
    assert result["count"] == 1


def test_list_devices_can_include_coordinator():
    result = server.list_devices(include_coordinator=True)
    assert result["count"] == 2


def test_find_devices_substring():
    result = server.find_devices("ikea")
    assert result["count"] == 1
    assert result["devices"][0]["friendly_name"] == "RGB Downlight"


def test_get_device_not_found():
    with pytest.raises(Z2MError, match="not found"):
        server.get_device("ghost")


async def test_get_device_state_reads_cache():
    result = await server.get_device_state("RGB Downlight")
    assert result["state"] == {"state": "OFF"}


def test_destructive_gate_blocks_when_disabled(monkeypatch):
    monkeypatch.setattr(server.settings, "allow_destructive", False)
    with pytest.raises(Z2MError, match="protected action"):
        server._require_destructive("remove_device")


def test_destructive_gate_allows_when_enabled(monkeypatch):
    monkeypatch.setattr(server.settings, "allow_destructive", True)
    server._require_destructive("remove_device")  # must not raise


async def test_all_expected_tools_registered():
    # FastMCP stores registered tools; ensure our full surface is present.
    tools = await server.mcp.list_tools()
    names = {t.name for t in tools}
    expected = {
        "connection_status", "list_devices", "find_devices", "get_device",
        "get_device_state", "list_groups", "get_bridge_info", "get_bridge_state",
        "get_bridge_health", "get_network_map", "set_device_state", "permit_join",
        "rename_device", "remove_device", "set_device_options", "configure_device",
        "ota_check", "ota_update", "create_group", "remove_group",
        "group_add_member", "group_remove_member",
    }
    assert expected <= names
