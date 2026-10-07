"""Narrow, TLS-only OpenClaw node transport for a media-only Pi.

This speaks the public Gateway v4 device handshake. It advertises one command,
not system.run or filesystem access. Server pairing and command approval remain
authoritative. A rejected or revoked connection never falls back to plaintext.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import json
from pathlib import Path
import ssl
import time
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from .gateway_identity import DeviceIdentity


COMMAND = "voiceassistant.audio"
Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
LifecycleHandler = Callable[[], Awaitable[None]]


def connect_request(
    identity: DeviceIdentity,
    *,
    nonce: str,
    signed_at_ms: int,
    device_token: str | None = None,
    bootstrap_token: str | None = None,
) -> dict[str, Any]:
    if device_token and bootstrap_token:
        raise ValueError("choose one Gateway credential")
    token = device_token or bootstrap_token or ""
    return {
        "type": "req",
        "id": str(uuid4()),
        "method": "connect",
        "params": {
            "minProtocol": 4,
            "maxProtocol": 4,
            "client": {
                "id": "node-host",
                "displayName": "OpenClaw Voice Assistant",
                "version": "0.1.0",
                "platform": "linux",
                "deviceFamily": "voiceassistant",
                "mode": "node",
                "instanceId": identity.device_id,
            },
            "caps": ["voiceassistant.audio"],
            "commands": [COMMAND],
            "role": "node",
            "scopes": [],
            "device": identity.connect_device(nonce, signed_at_ms, token),
            **(
                {"auth": {"deviceToken": device_token}}
                if device_token
                else {"auth": {"bootstrapToken": bootstrap_token}}
                if bootstrap_token
                else {}
            ),
        },
    }


def _frame(raw: str | bytes) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Gateway frame must be an object")
    return value


def invoke_params(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("paramsJSON")
    if raw is None:
        return {}
    if not isinstance(raw, str) or len(raw) > 1_000_000:
        raise ValueError("node invocation params are invalid or oversized")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("node invocation params must be an object")
    return value


class GatewayNode:
    def __init__(
        self,
        url: str,
        identity: DeviceIdentity,
        handler: Handler,
        *,
        token_path: Path,
        bootstrap_token_path: Path | None = None,
    ) -> None:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "wss"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("voiceassistant requires certificate-validated wss://")
        self.url = url
        self.identity = identity
        self.handler = handler
        self.token_path = token_path
        self.bootstrap_token_path = bootstrap_token_path
        self._send_lock = asyncio.Lock()
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def _read_secret(self, path: Path | None) -> str | None:
        if path is None:
            return None
        import stat

        try:
            state = path.lstat()
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(state.st_mode) or state.st_mode & 0o077:
            raise PermissionError("Gateway credential file is not private and regular")
        value = path.read_text(encoding="utf-8").strip()
        if not value or "\n" in value:
            raise ValueError("invalid Gateway credential")
        return value

    def _store_token(self, token: str) -> None:
        if not token or "\n" in token:
            raise ValueError("invalid Gateway token receipt")
        import os

        self.token_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.token_path.parent.stat().st_mode & 0o077:
            raise PermissionError("Gateway credential directory is not private")
        temporary = self.token_path.with_name(f".{self.token_path.name}.{uuid4().hex}.tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(token)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.token_path)
        finally:
            if temporary.exists():
                temporary.unlink()

    async def run_once(
        self,
        *,
        on_connected: LifecycleHandler | None = None,
        on_disconnected: LifecycleHandler | None = None,
    ) -> None:
        from websockets.asyncio.client import connect

        device_token = self._read_secret(self.token_path)
        bootstrap_token = None if device_token else self._read_secret(self.bootstrap_token_path)
        # The default context validates both certificate chain and hostname.
        context = ssl.create_default_context()
        async with connect(self.url, ssl=context, max_size=2_000_000, ping_interval=20) as socket:
            challenge = _frame(await asyncio.wait_for(socket.recv(), timeout=15))
            if challenge.get("type") != "event" or challenge.get("event") != "connect.challenge":
                raise RuntimeError("Gateway omitted connect challenge")
            payload = challenge.get("payload")
            if not isinstance(payload, dict):
                raise RuntimeError("Gateway challenge is malformed")
            nonce, signed_at = payload.get("nonce"), payload.get("ts")
            if not isinstance(nonce, str) or not isinstance(signed_at, int):
                raise RuntimeError("Gateway challenge is incomplete")
            if abs(int(time.time() * 1000) - signed_at) > 120_000:
                raise RuntimeError("Gateway challenge clock skew is too large")
            request = connect_request(
                self.identity,
                nonce=nonce,
                signed_at_ms=signed_at,
                device_token=device_token,
                bootstrap_token=bootstrap_token,
            )
            await socket.send(json.dumps(request, separators=(",", ":")))
            response = _frame(await asyncio.wait_for(socket.recv(), timeout=15))
            if response.get("type") != "res" or response.get("id") != request["id"]:
                raise RuntimeError("Gateway connect response did not match")
            if response.get("ok") is not True:
                error = response.get("error")
                code = error.get("code") if isinstance(error, dict) else "CONNECT_REJECTED"
                raise RuntimeError(f"Gateway rejected node connection: {code}")
            hello = response.get("payload")
            if not isinstance(hello, dict) or hello.get("type") != "hello-ok":
                raise RuntimeError("Gateway hello is malformed")
            auth = hello.get("auth")
            receipt = auth.get("deviceToken") if isinstance(auth, dict) else None
            if isinstance(receipt, str) and receipt != device_token:
                self._store_token(receipt)
            try:
                if on_connected is not None:
                    await on_connected()
                async for raw in socket:
                    frame = _frame(raw)
                    if frame.get("type") == "res":
                        pending = self._pending.pop(str(frame.get("id")), None)
                        if pending and not pending.done():
                            pending.set_result(frame)
                    elif frame.get("type") == "event" and frame.get("event") == "node.invoke.request":
                        task = asyncio.create_task(self._answer_invoke(socket, frame.get("payload")))
                        self._tasks.add(task)
                        task.add_done_callback(self._tasks.discard)
                        if len(self._tasks) > 8:
                            raise RuntimeError("too many concurrent node invocations")
            finally:
                for task in self._tasks:
                    task.cancel()
                await asyncio.gather(*self._tasks, return_exceptions=True)
                self._tasks.clear()
                for future in self._pending.values():
                    if not future.done():
                        future.set_exception(ConnectionError("Gateway disconnected"))
                self._pending.clear()
                if on_disconnected is not None:
                    await on_disconnected()

    async def _request(self, socket: Any, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = str(uuid4())
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        async with self._send_lock:
            await socket.send(json.dumps({"type": "req", "id": request_id, "method": method, "params": params}))
        try:
            return await asyncio.wait_for(future, timeout=5)
        finally:
            self._pending.pop(request_id, None)

    async def _answer_invoke(self, socket: Any, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        invoke_id = payload.get("id")
        node_id = payload.get("nodeId")
        command = payload.get("command")
        if not isinstance(invoke_id, str) or node_id != self.identity.device_id:
            return
        if command != COMMAND:
            result = {"id": invoke_id, "nodeId": node_id, "ok": False,
                      "error": {"code": "INVALID_REQUEST", "message": "command unavailable"}}
        else:
            try:
                answer = await self.handler(invoke_params(payload))
                result = {"id": invoke_id, "nodeId": node_id, "ok": True,
                          "payloadJSON": json.dumps(answer, separators=(",", ":"))}
            except Exception:
                result = {"id": invoke_id, "nodeId": node_id, "ok": False,
                          "error": {"code": "UNAVAILABLE", "message": "device media operation failed"}}
        response = await self._request(socket, "node.invoke.result", result)
        if response.get("ok") is not True:
            raise RuntimeError("Gateway rejected node invocation result")
