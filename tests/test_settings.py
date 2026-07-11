from zigbee2mqtt_mcp.settings import Settings


def test_ws_url_https_to_wss():
    s = Settings(Z2M_FRONTEND_URL="https://zigbee2mqtt.example.com")
    assert s.websocket_url() == "wss://zigbee2mqtt.example.com/api"


def test_ws_url_http_to_ws_and_strips_trailing_slash():
    s = Settings(Z2M_FRONTEND_URL="http://localhost:8080/")
    assert s.websocket_url() == "ws://localhost:8080/api"


def test_ws_url_with_base_path():
    s = Settings(Z2M_FRONTEND_URL="https://host.example.com/z2m")
    assert s.websocket_url() == "wss://host.example.com/z2m/api"


def test_ws_url_token_appended_and_redacted():
    s = Settings(
        Z2M_FRONTEND_URL="https://z.example.com", Z2M_AUTH_TOKEN="s3cret"
    )
    assert s.websocket_url() == "wss://z.example.com/api?token=s3cret"
    assert "s3cret" not in s.websocket_url(redacted=True)
    assert "token=***" in s.websocket_url(redacted=True)


def test_allowed_hosts_list_parsing():
    s = Settings(MCP_ALLOWED_HOSTS="*.strant.casa, localhost ,127.0.0.1")
    assert s.allowed_hosts_list() == ["*.strant.casa", "localhost", "127.0.0.1"]


def test_host_protection_value_mapping():
    assert Settings(MCP_HOST_PROTECTION="false").host_protection_value() is False
    assert Settings(MCP_HOST_PROTECTION="true").host_protection_value() is True
    assert Settings(MCP_HOST_PROTECTION="AUTO").host_protection_value() == "auto"
    assert Settings().host_protection_value() is False
