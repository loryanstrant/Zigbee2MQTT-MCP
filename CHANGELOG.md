# Changelog

All notable changes to this project are documented here. Versions use CalVer
(`YYYY.0M.MICRO`).

## [2026.7.0] - 2026-07-11

Initial release.

- MCP server for Zigbee2MQTT driven via the **frontend websocket API**
  (`ws(s)://<host>/api`) — no direct MQTT broker connection required.
- Persistent websocket client with a retained-state cache (devices, groups,
  bridge info/state/health, per-device state + availability), auto-reconnect,
  and cache re-priming.
- `bridge/request/*` → `bridge/response/*` calls correlated by transaction id
  with per-call timeouts.
- Read tools: `connection_status`, `list_devices`, `find_devices`, `get_device`,
  `get_device_state`, `list_groups`, `get_bridge_info`, `get_bridge_state`,
  `get_bridge_health`, `get_network_map`.
- Control tools: `set_device_state`, `ota_check`, and (behind
  `Z2M_ALLOW_DESTRUCTIVE`) `permit_join`, `rename_device`, `remove_device`,
  `set_device_options`, `configure_device`, `ota_update`, and group management.
- Streamable HTTP transport at `/mcp` (+ stdio); optional DNS-rebind host
  protection via `MCP_HOST_PROTECTION` / `MCP_ALLOWED_HOSTS`.
- Optional frontend `auth_token` support (`Z2M_AUTH_TOKEN`).
- Multi-arch (amd64/arm64) image published to GHCR via GitHub Actions.
