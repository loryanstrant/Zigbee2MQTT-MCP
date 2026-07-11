"""Configuration, loaded from environment variables (12-factor)."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    All values come from environment variables (or a local ``.env`` for dev).
    The upstream Zigbee2MQTT connection is expressed as a single frontend URL;
    the websocket URL (``ws(s)://.../api``) is derived from it.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Zigbee2MQTT frontend --------------------------------------------------
    frontend_url: str = Field(
        default="http://localhost:8080",
        validation_alias="Z2M_FRONTEND_URL",
        description="Base URL of the Zigbee2MQTT frontend, e.g. https://zigbee2mqtt.example.com",
    )
    auth_token: str = Field(
        default="",
        validation_alias="Z2M_AUTH_TOKEN",
        description="Frontend auth_token, appended as ?token=... when set. Empty = no auth.",
    )
    tls_insecure: bool = Field(
        default=False,
        validation_alias="Z2M_TLS_INSECURE",
        description="Skip TLS certificate verification for wss:// (self-signed certs).",
    )
    request_timeout: float = Field(
        default=15.0,
        validation_alias="Z2M_REQUEST_TIMEOUT",
        description="Seconds to wait for a bridge/response before timing out.",
    )
    connect_timeout: float = Field(
        default=20.0,
        validation_alias="Z2M_CONNECT_TIMEOUT",
        description="Seconds to wait for the initial connect + device snapshot at startup.",
    )
    allow_destructive: bool = Field(
        default=False,
        validation_alias="Z2M_ALLOW_DESTRUCTIVE",
        description="Enable destructive tools (remove device/group, permit_join, options).",
    )

    # --- MCP transport ---------------------------------------------------------
    transport: str = Field(
        default="http",
        validation_alias="MCP_TRANSPORT",
        description="MCP transport: 'http' (streamable HTTP) or 'stdio'.",
    )
    host: str = Field(default="0.0.0.0", validation_alias="MCP_HOST")
    port: int = Field(default=8080, validation_alias="MCP_PORT")
    path: str = Field(default="/mcp", validation_alias="MCP_PATH")
    allowed_hosts: str = Field(
        default="*.strant.casa,localhost,127.0.0.1",
        validation_alias="MCP_ALLOWED_HOSTS",
        description="Comma-separated Host header allowlist (used when host protection is on).",
    )
    host_protection: str = Field(
        default="false",
        validation_alias="MCP_HOST_PROTECTION",
        description=(
            "DNS-rebind Host/Origin protection: 'false' (default, no checks), "
            "'true'/'strict', or 'auto'. When enabled, only MCP_ALLOWED_HOSTS "
            "may appear in the Host header."
        ),
    )
    log_level: str = Field(default="INFO", validation_alias="MCP_LOG_LEVEL")

    # --- derived helpers -------------------------------------------------------
    def websocket_url(self, *, redacted: bool = False) -> str:
        """Derive the ``ws(s)://host[:port]/api`` URL from ``frontend_url``.

        When ``redacted`` is True the auth token is replaced with ``***`` so the
        URL is safe to log.
        """
        parts = urlsplit(self.frontend_url)
        scheme = "wss" if parts.scheme == "https" else "ws"
        base_path = parts.path.rstrip("/")
        query = ""
        if self.auth_token:
            query = "token=***" if redacted else f"token={self.auth_token}"
        return urlunsplit((scheme, parts.netloc, f"{base_path}/api", query, ""))

    def allowed_hosts_list(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]

    def host_protection_value(self) -> bool | Literal["auto"]:
        """Map MCP_HOST_PROTECTION to FastMCP's host_origin_protection arg."""
        value = self.host_protection.strip().lower()
        if value == "auto":
            return "auto"
        return value in ("1", "true", "yes", "on", "strict")
