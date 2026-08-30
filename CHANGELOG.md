# Changelog

All notable changes to this project are documented here. Versions use CalVer
(`YYYY.0M.MICRO`).

## [2026.8.0] - 2026-08-30

Fixes unbounded memory growth over the HTTP transport.

### Fixed

- **Memory leak with clients that never terminate their session.** The streamable
  HTTP transport ran stateful, and the MCP SDK only releases a session's transport
  when the client sends `DELETE /mcp` — never on a dropped connection. A gateway
  that opens a fresh session per connection therefore grew the server without
  bound; one deployment reached **2.9 GB across 27,662 retained sessions** with
  zero DELETEs in 43 days. HTTP is now **stateless by default**, creating and
  disposing a transport per request. Nothing is lost: all state lives in the
  shared websocket client, not in the session. Override with `MCP_STATELESS=false`.
- `set_device_state(wait=True)` leaked its waiter `Future` on timeout — the
  cleanup line was a no-op expression that removed nothing. Waiters are now
  discarded in a `finally`.
- The per-topic state and availability caches accepted any topic as a key and
  never dropped entries for renamed or removed devices. They are now bounded to
  the friendly names the bridge publishes, and pruned on each roster snapshot.

### Added

- `MCP_STATELESS` (default `true`) to control the HTTP session model.
- `mem_limit: 512m` in the example `compose.yaml`, as a backstop against any
  future memory regression.
- The startup log line now reports `stateless=…`, so the running session model
  is visible in `docker logs`.

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
