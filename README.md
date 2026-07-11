# Zigbee2MQTT-MCP

An [MCP](https://modelcontextprotocol.io) server for
[Zigbee2MQTT](https://www.zigbee2mqtt.io). It lets an LLM (or any MCP client)
list and inspect your Zigbee devices, read and change their state, and manage
the bridge — all through the Zigbee2MQTT **frontend websocket API**, so it needs
no direct access to your MQTT broker.

## Why the frontend API?

Zigbee2MQTT's frontend exposes a websocket at `/api` that proxies MQTT traffic
as JSON `{"topic": ..., "payload": ...}` messages (base topic already stripped).
Talking to it instead of the MQTT broker means:

- **No broker dependency** — works even if you don't expose MQTT on the network.
- **One HTTPS endpoint** — reuses your existing reverse proxy / TLS.
- **Auth-ready** — supports the frontend `auth_token` when you enable it.

Requests that change the bridge (`bridge/request/*`) are correlated to their
`bridge/response/*` reply via a transaction id, with per-call timeouts. The
retained device snapshot is cached on connect, so reads are instant and the
connection auto-reconnects (re-priming the cache) if it drops.

## Tools

**Read**

| Tool | Description |
|------|-------------|
| `connection_status` | Websocket health + cache readiness |
| `list_devices` | All devices (compact summary or `detailed=true`) |
| `find_devices` | Search by name / model / vendor / address |
| `get_device` | Full definition/metadata for one device |
| `get_device_state` | Current cached state (+ optional `refresh`) |
| `list_groups` | All groups and their members |
| `get_bridge_info` | Version, coordinator, config, permit-join state |
| `get_bridge_state` / `get_bridge_health` | Bridge online state / health metrics |
| `get_network_map` | Scan and return the Zigbee mesh map |

**Control**

| Tool | Description |
|------|-------------|
| `set_device_state` | Set state — `{"state":"ON"}`, brightness, colour, cover position, … |
| `ota_check` | Check for a firmware update |
| `permit_join`* | Allow/deny new devices joining |
| `rename_device`* | Rename a device |
| `remove_device`* | Unpair a device |
| `set_device_options`* / `configure_device`* | Per-device options / re-configure |
| `ota_update`* | Perform a firmware update |
| `create_group`* / `remove_group`* / `group_add_member`* / `group_remove_member`* | Group management |

\* Protected: disabled unless `Z2M_ALLOW_DESTRUCTIVE=true`. Reads and
`set_device_state` are always available.

## Configuration

All configuration is via environment variables (see [`.env.example`](.env.example)):

| Variable | Default | Description |
|----------|---------|-------------|
| `Z2M_FRONTEND_URL` | `http://localhost:8080` | Base URL of the Zigbee2MQTT frontend. `ws(s)://…/api` is derived from it |
| `Z2M_AUTH_TOKEN` | *(empty)* | Frontend `auth_token`, appended as `?token=…` |
| `Z2M_TLS_INSECURE` | `false` | Skip TLS verification for `wss://` (self-signed) |
| `Z2M_REQUEST_TIMEOUT` | `15` | Seconds to wait for a `bridge/response` |
| `Z2M_CONNECT_TIMEOUT` | `20` | Seconds to wait for the initial snapshot at startup |
| `Z2M_ALLOW_DESTRUCTIVE` | `false` | Enable the protected management tools |
| `MCP_TRANSPORT` | `http` | `http` (streamable HTTP) or `stdio` |
| `MCP_HOST` / `MCP_PORT` / `MCP_PATH` | `0.0.0.0` / `8080` / `/mcp` | HTTP bind + path |
| `MCP_HOST_PROTECTION` | `false` | DNS-rebind Host/Origin protection: `false`, `true`, or `auto` |
| `MCP_ALLOWED_HOSTS` | `*.strant.casa,localhost,127.0.0.1` | Host allowlist (used when protection is on) |
| `MCP_LOG_LEVEL` | `INFO` | Log level |

## Running

### Docker (recommended)

```bash
docker run -d --name zigbee2mqtt-mcp -p 8080:8080 \
  -e Z2M_FRONTEND_URL=https://zigbee2mqtt.example.com \
  ghcr.io/loryanstrant/zigbee2mqtt-mcp:latest
```

The MCP endpoint is then at `http://<host>:8080/mcp`.

Or with Compose — copy `.env.example` to `.env`, edit it, and:

```bash
docker compose up -d
```

### Local (Python 3.11+)

```bash
pip install .
Z2M_FRONTEND_URL=https://zigbee2mqtt.example.com python -m zigbee2mqtt_mcp
```

### stdio (local MCP client, e.g. Claude Desktop)

```json
{
  "mcpServers": {
    "zigbee2mqtt": {
      "command": "python",
      "args": ["-m", "zigbee2mqtt_mcp"],
      "env": {
        "MCP_TRANSPORT": "stdio",
        "Z2M_FRONTEND_URL": "https://zigbee2mqtt.example.com"
      }
    }
  }
}
```

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Security

This server exposes control of your Zigbee network. Bind it to a trusted
network (LAN/VPN) or an authenticating proxy, keep `Z2M_ALLOW_DESTRUCTIVE=false`
unless you need management tools, and never commit a populated `.env`. See
[SECURITY.md](SECURITY.md).

## License

MIT — see [LICENSE](LICENSE).
