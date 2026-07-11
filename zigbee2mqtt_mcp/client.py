"""Async client for the Zigbee2MQTT frontend websocket API.

The Zigbee2MQTT frontend exposes a websocket at ``/api`` that proxies MQTT
traffic as JSON messages of the form ``{"topic": ..., "payload": ...}``, with
the configured base topic already stripped. On connect it replays a retained
snapshot (bridge/devices, bridge/info, bridge/groups, per-device state, ...),
and thereafter pushes live updates the same way.

This client keeps a single persistent connection, caches the retained state so
reads are served locally, and issues ``bridge/request/*`` calls correlated to
their ``bridge/response/*`` reply via a ``transaction`` id.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import ssl
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from .settings import Settings

logger = logging.getLogger("zigbee2mqtt_mcp.client")


class Z2MError(RuntimeError):
    """Raised when Zigbee2MQTT returns an error or a request cannot be completed."""


class Z2MNotReady(Z2MError):
    """Raised when a read is attempted before the device snapshot has arrived."""


class Z2MClient:
    """Persistent websocket client with a retained-state cache."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._ws: websockets.ClientConnection | None = None
        self._run_task: asyncio.Task[None] | None = None
        self._stopping = False

        # connection / readiness signalling
        self._connected = asyncio.Event()
        self._primed = asyncio.Event()  # set once bridge/devices has been seen

        # retained-state caches (bare topics, base topic already stripped)
        self.devices: list[dict[str, Any]] = []
        self.groups: list[dict[str, Any]] = []
        self.bridge_info: dict[str, Any] = {}
        self.bridge_state: Any = None
        self.bridge_health: dict[str, Any] = {}
        self.definitions: dict[str, Any] = {}
        self.device_state: dict[str, Any] = {}
        self.availability: dict[str, Any] = {}

        # bridge/request -> bridge/response correlation
        self._txn_counter = 0
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        # one-shot waiters for the next state update of a device
        self._state_waiters: dict[str, list[asyncio.Future[dict[str, Any]]]] = {}

    # -- lifecycle -------------------------------------------------------------

    async def start(self) -> None:
        """Start the background connection loop and wait (best effort) for the
        first device snapshot. Never raises on connect failure — the loop keeps
        retrying and tools surface a clear error until data arrives."""
        self._stopping = False
        self._run_task = asyncio.create_task(self._run(), name="z2m-ws")
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(
                self._primed.wait(), timeout=self._settings.connect_timeout
            )
        if not self._primed.is_set():
            logger.warning(
                "Started without a device snapshot yet (upstream unreachable?); "
                "will keep retrying in the background."
            )

    async def stop(self) -> None:
        self._stopping = True
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
        if self._run_task is not None:
            self._run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._run_task
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.cancel()
        self._pending.clear()

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    @property
    def primed(self) -> bool:
        return self._primed.is_set()

    def status(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "primed": self.primed,
            "websocket_url": self._settings.websocket_url(redacted=True),
            "device_count": len(self.devices),
            "group_count": len(self.groups),
            "allow_destructive": self._settings.allow_destructive,
        }

    # -- connection loop -------------------------------------------------------

    def _ssl_context(self) -> ssl.SSLContext | None:
        if not self._settings.websocket_url().startswith("wss://"):
            return None
        ctx = ssl.create_default_context()
        if self._settings.tls_insecure:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return ctx

    async def _run(self) -> None:
        backoff = 1.0
        while not self._stopping:
            try:
                async with websockets.connect(
                    self._settings.websocket_url(),
                    ssl=self._ssl_context(),
                    open_timeout=self._settings.connect_timeout,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=16 * 1024 * 1024,
                ) as ws:
                    self._ws = ws
                    self._connected.set()
                    backoff = 1.0
                    logger.info(
                        "Connected to Zigbee2MQTT at %s",
                        self._settings.websocket_url(redacted=True),
                    )
                    async for raw in ws:
                        self._handle(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - loop must survive any error
                if self._stopping:
                    break
                logger.warning("Websocket connection lost (%s); reconnecting…", exc)
            finally:
                self._connected.clear()
                self._ws = None
                # a fresh connection replays the whole snapshot, so treat the
                # cache as stale until the next bridge/devices arrives.
                self._primed.clear()

            if self._stopping:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    # -- inbound message routing ----------------------------------------------

    def _handle(self, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            logger.debug("Ignoring non-JSON frame: %r", raw[:80])
            return
        if not isinstance(msg, dict):
            return
        topic = msg.get("topic")
        payload = msg.get("payload")
        if not isinstance(topic, str):
            return

        if topic == "bridge/devices":
            self.devices = payload if isinstance(payload, list) else []
            self._primed.set()
        elif topic == "bridge/groups":
            self.groups = payload if isinstance(payload, list) else []
        elif topic == "bridge/info":
            self.bridge_info = payload if isinstance(payload, dict) else {}
        elif topic == "bridge/state":
            # newer Z2M sends {"state": "online"}, older sends a bare string
            self.bridge_state = payload
        elif topic == "bridge/health":
            self.bridge_health = payload if isinstance(payload, dict) else {}
        elif topic == "bridge/definitions":
            self.definitions = payload if isinstance(payload, dict) else {}
        elif topic.startswith("bridge/response/"):
            self._resolve_response(topic, payload)
        elif topic.startswith("bridge/"):
            # bridge/logging, bridge/converters, bridge/extensions, … — not cached
            pass
        elif topic.endswith("/availability"):
            name = topic[: -len("/availability")]
            self.availability[name] = payload
        else:
            # a device state update, keyed by friendly name
            self.device_state[topic] = payload
            self._resolve_state_waiters(topic, payload)

    def _resolve_response(self, topic: str, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        txn = payload.get("transaction")
        if txn is None:
            return
        fut = self._pending.pop(str(txn), None)
        if fut is not None and not fut.done():
            fut.set_result(payload)

    def _resolve_state_waiters(self, name: str, payload: Any) -> None:
        waiters = self._state_waiters.pop(name, [])
        for fut in waiters:
            if not fut.done():
                fut.set_result(payload if isinstance(payload, dict) else {})

    # -- outbound --------------------------------------------------------------

    async def _ensure_connected(self) -> None:
        try:
            await asyncio.wait_for(
                self._connected.wait(), timeout=self._settings.request_timeout
            )
        except asyncio.TimeoutError as exc:
            raise Z2MError("Not connected to Zigbee2MQTT") from exc

    async def _send(self, topic: str, payload: Any) -> None:
        await self._ensure_connected()
        assert self._ws is not None
        try:
            await self._ws.send(json.dumps({"topic": topic, "payload": payload}))
        except ConnectionClosed as exc:
            raise Z2MError("Connection closed while sending") from exc

    def _next_txn(self) -> str:
        self._txn_counter += 1
        return f"z2mmcp-{self._txn_counter}"

    async def request(
        self,
        endpoint: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Issue a ``bridge/request/<endpoint>`` and await its response.

        Returns the response payload (``{"status", "data", "transaction", ...}``).
        Raises :class:`Z2MError` on an error status or timeout.
        """
        txn = self._next_txn()
        body: dict[str, Any] = dict(payload or {})
        body["transaction"] = txn
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[txn] = fut
        try:
            await self._send(f"bridge/request/{endpoint}", body)
            response = await asyncio.wait_for(
                fut, timeout=timeout or self._settings.request_timeout
            )
        except asyncio.TimeoutError as exc:
            raise Z2MError(
                f"Timed out waiting for response to bridge/request/{endpoint}"
            ) from exc
        finally:
            self._pending.pop(txn, None)

        if response.get("status") == "error":
            raise Z2MError(
                response.get("error") or f"bridge/request/{endpoint} failed"
            )
        return response

    async def set_state(
        self, friendly_name: str, payload: dict[str, Any], *, wait: bool = True
    ) -> dict[str, Any]:
        """Publish ``<friendly_name>/set`` and optionally return the new state.

        Zigbee2MQTT reports the result asynchronously as a device-state update;
        when ``wait`` is set we return the next state update (or the cached
        state on timeout).
        """
        waiter: asyncio.Future[dict[str, Any]] | None = None
        if wait:
            loop = asyncio.get_running_loop()
            waiter = loop.create_future()
            self._state_waiters.setdefault(friendly_name, []).append(waiter)

        await self._send(f"{friendly_name}/set", payload)

        if waiter is None:
            return {}
        try:
            return await asyncio.wait_for(
                waiter, timeout=self._settings.request_timeout
            )
        except asyncio.TimeoutError:
            self._state_waiters.get(friendly_name, [])
            return self.device_state.get(friendly_name, {}) or {}

    async def refresh_state(self, friendly_name: str) -> None:
        """Ask the device to re-report its state via ``<name>/get`` (best effort)."""
        await self._send(f"{friendly_name}/get", {"state": ""})

    # -- cache lookups ---------------------------------------------------------

    def _require_primed(self) -> None:
        if not self._primed.is_set():
            raise Z2MNotReady(
                "Zigbee2MQTT device list not yet received; the server is still "
                "connecting to the frontend."
            )

    def find_device(self, name_or_ieee: str) -> dict[str, Any] | None:
        self._require_primed()
        key = name_or_ieee.lower()
        for dev in self.devices:
            if (
                str(dev.get("friendly_name", "")).lower() == key
                or str(dev.get("ieee_address", "")).lower() == key
            ):
                return dev
        return None
