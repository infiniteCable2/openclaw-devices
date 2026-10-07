"""Minimal native OpenClaw node identity and v3 challenge signing.

The private key lives only in device-local state. This module deliberately does
not grant tools, select an agent, or invent a second account namespace.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class DeviceIdentity:
    private_key: Ed25519PrivateKey

    @property
    def public_key_raw(self) -> bytes:
        return self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    @property
    def device_id(self) -> str:
        return hashlib.sha256(self.public_key_raw).hexdigest()

    @property
    def public_key_base64url(self) -> str:
        return _b64url(self.public_key_raw)

    @classmethod
    def load_or_create(cls, path: Path) -> DeviceIdentity:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        parent = path.parent.stat()
        if parent.st_mode & 0o077:
            raise PermissionError("device identity directory must be private")
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(path, flags, 0o600)
        except FileExistsError:
            current = path.lstat()
            if not stat.S_ISREG(current.st_mode) or current.st_mode & 0o077:
                raise PermissionError("device identity file is not private and regular")
            raw = path.read_bytes()
            if len(raw) != 32:
                raise ValueError("invalid device identity length")
            return cls(Ed25519PrivateKey.from_private_bytes(raw))
        key = Ed25519PrivateKey.generate()
        raw = key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        return cls(key)

    def connect_device(self, nonce: str, signed_at_ms: int, token: str = "") -> dict[str, object]:
        if not nonce or "|" in nonce or signed_at_ms < 0:
            raise ValueError("invalid Gateway challenge")
        # packages/gateway-client/src/device-auth.ts owns this byte contract.
        payload = "|".join(
            (
                "v3",
                self.device_id,
                "node-host",
                "node",
                "node",
                "",
                str(signed_at_ms),
                token,
                nonce,
                "linux",
                "voiceassistant",
            )
        )
        return {
            "id": self.device_id,
            "publicKey": self.public_key_base64url,
            "signature": _b64url(self.private_key.sign(payload.encode("utf-8"))),
            "signedAt": signed_at_ms,
            "nonce": nonce,
        }
