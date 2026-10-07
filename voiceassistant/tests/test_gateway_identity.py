import os
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from openclaw_voiceassistant.gateway_identity import DeviceIdentity


class GatewayIdentityTests(unittest.TestCase):
    def test_stable_private_device_identity(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "state" / "identity.key"
            first = DeviceIdentity.load_or_create(path)
            second = DeviceIdentity.load_or_create(path)
            self.assertEqual(first.device_id, second.device_id)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_connect_signature_matches_gateway_v3_bytes(self) -> None:
        identity = DeviceIdentity(Ed25519PrivateKey.from_private_bytes(bytes(range(32))))
        signed = identity.connect_device("challenge", 1234, "device-token")
        self.assertEqual(signed["id"], identity.device_id)
        import base64

        signature = base64.urlsafe_b64decode(str(signed["signature"]) + "==")
        payload = (
            f"v3|{identity.device_id}|node-host|node|node||1234|device-token|challenge|linux|voiceassistant"
        )
        identity.private_key.public_key().verify(signature, payload.encode())

    def test_rejects_public_identity_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "state" / "identity.key"
            DeviceIdentity.load_or_create(path)
            os.chmod(path, 0o644)
            with self.assertRaises(PermissionError):
                DeviceIdentity.load_or_create(path)


if __name__ == "__main__":
    unittest.main()
