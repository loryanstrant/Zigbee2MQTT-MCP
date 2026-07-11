# Security policy

## Reporting a vulnerability

Please report security issues privately via GitHub's **Report a vulnerability**
button (Security → Advisories) on this repository, rather than opening a public
issue. Include a description, affected version, and reproduction steps.

## Security model

This server exposes control of a Zigbee network to any MCP client that can reach
it. Treat it as a privileged endpoint:

- **Network exposure.** Bind it to a trusted network only (LAN/VPN) or place it
  behind an authenticating reverse proxy. The `MCP_ALLOWED_HOSTS` allowlist
  mitigates DNS-rebinding but is **not** authentication.
- **Destructive actions are off by default.** Device/group management,
  `permit_join`, OTA updates, and per-device options require
  `Z2M_ALLOW_DESTRUCTIVE=true`. Leave it off unless you intend to expose
  network management to the LLM. Reads and `set_device_state` remain available.
- **Upstream auth.** When your Zigbee2MQTT frontend has an `auth_token`, set
  `Z2M_AUTH_TOKEN`; it is sent to the frontend and never logged (the websocket
  URL is redacted in logs).
- **No secrets in the image.** All configuration is via environment variables;
  never bake tokens into the image or commit a populated `.env`.
