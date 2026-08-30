"""Entry point: select the MCP transport from configuration."""

from __future__ import annotations

import logging

from .server import mcp, settings

logger = logging.getLogger("zigbee2mqtt_mcp")


def main() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    transport = settings.transport.lower()
    if transport == "stdio":
        mcp.run(transport="stdio")
        return

    # HTTP (streamable) transport. Host/Origin (DNS-rebind) protection is off by
    # default so the server works behind any reverse proxy; enable it with
    # MCP_HOST_PROTECTION and constrain MCP_ALLOWED_HOSTS to harden.
    #
    # Stateless by default: a stateful session is only released when the client
    # sends DELETE, and clients that just drop the connection instead leave the
    # transport resident for the life of the process. Nothing here is per-session
    # (all state lives in the shared Z2MClient), so a transport per request costs
    # nothing and keeps memory flat. See MCP_STATELESS.
    logger.info(
        "Starting Zigbee2MQTT MCP (http) on %s:%s%s, upstream=%s, "
        "host_protection=%s, stateless=%s",
        settings.host,
        settings.port,
        settings.path,
        settings.websocket_url(redacted=True),
        settings.host_protection,
        settings.stateless,
    )
    mcp.run(
        transport="http",
        host=settings.host,
        port=settings.port,
        path=settings.path,
        stateless=settings.stateless,
        host_origin_protection=settings.host_protection_value(),
        allowed_hosts=settings.allowed_hosts_list(),
    )


if __name__ == "__main__":
    main()
