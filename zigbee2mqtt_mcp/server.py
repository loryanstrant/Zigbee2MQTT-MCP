"""FastMCP server exposing Zigbee2MQTT tools.

Reads are served from the client's retained-state cache; control actions are
issued over the frontend websocket. Destructive actions are gated behind the
``Z2M_ALLOW_DESTRUCTIVE`` setting.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP

from .client import Z2MClient, Z2MError
from .settings import Settings

logger = logging.getLogger("zigbee2mqtt_mcp.server")

settings = Settings()
client = Z2MClient(settings)


@asynccontextmanager
async def _lifespan(_server: FastMCP):
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    await client.start()
    try:
        yield {"client": client}
    finally:
        await client.stop()


INSTRUCTIONS = """\
Control and inspect a Zigbee2MQTT network via its frontend websocket API.

Use `list_devices` / `get_device_state` to discover devices and read their
current values, and `set_device_state` to change them (e.g. turn a light on,
set brightness/colour, or move a cover). Bridge management tools (permit_join,
rename/remove device, groups, OTA) are available; the state-changing ones
require the server to be started with Z2M_ALLOW_DESTRUCTIVE=true.
"""

mcp: FastMCP = FastMCP("Zigbee2MQTT", instructions=INSTRUCTIONS, lifespan=_lifespan)


# --- helpers -----------------------------------------------------------------

def _require_destructive(action: str) -> None:
    if not settings.allow_destructive:
        raise Z2MError(
            f"'{action}' is a protected action and is disabled. Set "
            "Z2M_ALLOW_DESTRUCTIVE=true to enable device/group management tools."
        )


def _exposes_summary(definition: dict[str, Any] | None) -> list[str]:
    """Flatten a device definition's exposes into a list of property names."""
    props: list[str] = []
    for expose in (definition or {}).get("exposes", []) or []:
        if isinstance(expose, dict):
            if "features" in expose and isinstance(expose["features"], list):
                for feat in expose["features"]:
                    name = feat.get("property") or feat.get("name")
                    if name:
                        props.append(str(name))
            else:
                name = expose.get("property") or expose.get("name")
                if name:
                    props.append(str(name))
    # de-dup, preserve order
    seen: set[str] = set()
    return [p for p in props if not (p in seen or seen.add(p))]


def _device_summary(dev: dict[str, Any]) -> dict[str, Any]:
    definition = dev.get("definition") or {}
    name = dev.get("friendly_name")
    return {
        "friendly_name": name,
        "ieee_address": dev.get("ieee_address"),
        "type": dev.get("type"),
        "model": definition.get("model") or dev.get("model_id"),
        "vendor": definition.get("vendor") or dev.get("manufacturer"),
        "description": definition.get("description"),
        "power_source": dev.get("power_source"),
        "disabled": dev.get("disabled", False),
        "supported": dev.get("supported", None),
        "interviewing": dev.get("interview_completed") is False,
        "exposes": _exposes_summary(definition),
        "availability": client.availability.get(str(name)),
    }


# --- read tools --------------------------------------------------------------

@mcp.tool
def connection_status() -> dict[str, Any]:
    """Report websocket connection health and cache readiness."""
    return client.status()


@mcp.tool
def list_devices(detailed: bool = False, include_coordinator: bool = False) -> dict[str, Any]:
    """List all Zigbee devices known to the bridge.

    Set ``detailed`` to return the raw device objects; otherwise a compact
    summary (name, address, model, vendor, exposed properties, availability) is
    returned. The coordinator itself is excluded unless ``include_coordinator``.
    """
    client._require_primed()
    devices = client.devices
    if not include_coordinator:
        devices = [d for d in devices if d.get("type") != "Coordinator"]
    if detailed:
        return {"count": len(devices), "devices": devices}
    return {"count": len(devices), "devices": [_device_summary(d) for d in devices]}


@mcp.tool
def find_devices(query: str) -> dict[str, Any]:
    """Find devices whose friendly name, model, vendor, or address matches ``query`` (case-insensitive substring)."""
    client._require_primed()
    q = query.lower()
    matches = []
    for dev in client.devices:
        definition = dev.get("definition") or {}
        haystack = " ".join(
            str(x)
            for x in (
                dev.get("friendly_name"),
                dev.get("ieee_address"),
                definition.get("model"),
                definition.get("vendor"),
                definition.get("description"),
            )
            if x
        ).lower()
        if q in haystack:
            matches.append(_device_summary(dev))
    return {"count": len(matches), "devices": matches}


@mcp.tool
def get_device(device: str) -> dict[str, Any]:
    """Get the full definition/metadata for a single device by friendly name or IEEE address."""
    dev = client.find_device(device)
    if dev is None:
        raise Z2MError(f"Device not found: {device}")
    return dev


@mcp.tool
async def get_device_state(device: str, refresh: bool = False) -> dict[str, Any]:
    """Get the current state of a device (cached).

    With ``refresh=True`` the device is asked to re-report first (best effort;
    battery/sleepy devices may not respond immediately).
    """
    dev = client.find_device(device)
    name = str(dev["friendly_name"]) if dev else device
    if refresh:
        try:
            await client.refresh_state(name)
        except Z2MError:
            pass
    return {
        "friendly_name": name,
        "state": client.device_state.get(name, {}),
        "availability": client.availability.get(name),
    }


@mcp.tool
def list_groups() -> dict[str, Any]:
    """List all Zigbee2MQTT groups and their members."""
    client._require_primed()
    return {"count": len(client.groups), "groups": client.groups}


@mcp.tool
def get_bridge_info() -> dict[str, Any]:
    """Get bridge/coordinator info: version, coordinator type, config, permit-join state."""
    return client.bridge_info


@mcp.tool
def get_bridge_state() -> dict[str, Any]:
    """Get the bridge online/offline state."""
    return {"state": client.bridge_state}


@mcp.tool
def get_bridge_health() -> dict[str, Any]:
    """Get bridge health metrics (if the Zigbee2MQTT version publishes them)."""
    return client.bridge_health


@mcp.tool
async def get_network_map(map_type: str = "raw", routes: bool = False, timeout: float = 60.0) -> dict[str, Any]:
    """Build the Zigbee network map. ``map_type`` is 'raw', 'graphviz', or 'plantuml'.

    This scans the mesh and can take tens of seconds on large networks.
    """
    resp = await client.request(
        "networkmap",
        {"type": map_type, "routes": routes},
        timeout=timeout,
    )
    return resp.get("data", resp)


# --- control tools -----------------------------------------------------------

@mcp.tool
async def set_device_state(device: str, state: dict[str, Any], wait: bool = True) -> dict[str, Any]:
    """Set a device's state. ``state`` is a Zigbee2MQTT set-payload.

    Examples: {"state": "ON"}, {"brightness": 128}, {"color": {"hex": "#FF0000"}},
    {"position": 50} for a cover. When ``wait`` is true the resulting device
    state is returned.
    """
    dev = client.find_device(device)
    name = str(dev["friendly_name"]) if dev else device
    new_state = await client.set_state(name, state, wait=wait)
    return {"friendly_name": name, "state": new_state}


@mcp.tool
async def permit_join(enable: bool, time: int | None = None, device: str | None = None) -> dict[str, Any]:
    """Enable or disable joining of new devices (optionally time-limited / via a specific router). Protected."""
    _require_destructive("permit_join")
    payload: dict[str, Any] = {"value": enable}
    if time is not None:
        payload["time"] = time
    if device is not None:
        payload["device"] = device
    resp = await client.request("permit_join", payload)
    return resp.get("data", resp)


@mcp.tool
async def rename_device(current: str, new_name: str) -> dict[str, Any]:
    """Rename a device's friendly name. Protected."""
    _require_destructive("rename_device")
    resp = await client.request(
        "device/rename", {"from": current, "to": new_name}
    )
    return resp.get("data", resp)


@mcp.tool
async def remove_device(device: str, force: bool = False, block: bool = False) -> dict[str, Any]:
    """Remove (unpair) a device from the network. ``force`` removes from the DB even if it doesn't respond. Protected."""
    _require_destructive("remove_device")
    resp = await client.request(
        "device/remove", {"id": device, "force": force, "block": block}
    )
    return resp.get("data", resp)


@mcp.tool
async def set_device_options(device: str, options: dict[str, Any]) -> dict[str, Any]:
    """Set per-device options (e.g. debounce, calibration, reporting). Protected."""
    _require_destructive("set_device_options")
    resp = await client.request(
        "device/options", {"id": device, "options": options}
    )
    return resp.get("data", resp)


@mcp.tool
async def configure_device(device: str) -> dict[str, Any]:
    """Re-run device configuration/binding/reporting setup. Protected."""
    _require_destructive("configure_device")
    resp = await client.request("device/configure", {"id": device})
    return resp.get("data", resp)


@mcp.tool
async def ota_check(device: str) -> dict[str, Any]:
    """Check whether a firmware (OTA) update is available for a device."""
    resp = await client.request("device/ota_update/check", {"id": device})
    return resp.get("data", resp)


@mcp.tool
async def ota_update(device: str, timeout: float = 600.0) -> dict[str, Any]:
    """Perform a firmware (OTA) update for a device. Can take many minutes. Protected."""
    _require_destructive("ota_update")
    resp = await client.request(
        "device/ota_update/update", {"id": device}, timeout=timeout
    )
    return resp.get("data", resp)


@mcp.tool
async def create_group(name: str, group_id: int | None = None) -> dict[str, Any]:
    """Create a new group. Protected."""
    _require_destructive("create_group")
    payload: dict[str, Any] = {"friendly_name": name}
    if group_id is not None:
        payload["id"] = group_id
    resp = await client.request("group/add", payload)
    return resp.get("data", resp)


@mcp.tool
async def remove_group(group: str, force: bool = False) -> dict[str, Any]:
    """Remove a group. Protected."""
    _require_destructive("remove_group")
    resp = await client.request("group/remove", {"id": group, "force": force})
    return resp.get("data", resp)


@mcp.tool
async def group_add_member(group: str, device: str) -> dict[str, Any]:
    """Add a device to a group. Protected."""
    _require_destructive("group_add_member")
    resp = await client.request("group/members/add", {"group": group, "device": device})
    return resp.get("data", resp)


@mcp.tool
async def group_remove_member(group: str, device: str) -> dict[str, Any]:
    """Remove a device from a group. Protected."""
    _require_destructive("group_remove_member")
    resp = await client.request(
        "group/members/remove", {"group": group, "device": device}
    )
    return resp.get("data", resp)
