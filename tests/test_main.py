import pytest

import zigbee2mqtt_mcp.__main__ as entry
from zigbee2mqtt_mcp.settings import Settings


@pytest.fixture
def captured_run(monkeypatch):
    """Capture the kwargs main() hands to FastMCP without starting a server."""
    calls: list[dict] = []

    def fake_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(entry.mcp, "run", fake_run)
    return calls


def _use(monkeypatch, **env) -> None:
    monkeypatch.setattr(entry, "settings", Settings(**env))


def test_http_transport_runs_stateless_by_default(captured_run, monkeypatch):
    _use(monkeypatch, MCP_TRANSPORT="http")
    entry.main()
    assert captured_run[0]["transport"] == "http"
    assert captured_run[0]["stateless"] is True


def test_stateless_can_be_disabled(captured_run, monkeypatch):
    _use(monkeypatch, MCP_TRANSPORT="http", MCP_STATELESS="false")
    entry.main()
    assert captured_run[0]["stateless"] is False


def test_stdio_transport_takes_no_http_kwargs(captured_run, monkeypatch):
    _use(monkeypatch, MCP_TRANSPORT="stdio")
    entry.main()
    assert captured_run == [{"transport": "stdio"}]
