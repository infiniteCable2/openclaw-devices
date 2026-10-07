import tempfile
from pathlib import Path
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from openclaw_voiceassistant.gateway_identity import DeviceIdentity
from openclaw_voiceassistant.gateway_node import COMMAND, GatewayNode, connect_request, invoke_params


class GatewayNodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = DeviceIdentity(Ed25519PrivateKey.from_private_bytes(bytes(range(32))))

    def test_connect_advertises_only_media_command(self) -> None:
        request = connect_request(self.identity, nonce="n", signed_at_ms=42)
        params = request["params"]
        self.assertEqual(params["role"], "node")
        self.assertEqual(params["scopes"], [])
        self.assertEqual(params["commands"], [COMMAND])
        self.assertEqual(params["client"]["mode"], "node")

    def test_initial_shared_gateway_token_is_not_mistaken_for_setup_bootstrap(self) -> None:
        request = connect_request(self.identity, nonce="n", signed_at_ms=42,
                                  gateway_token="initial-token")
        self.assertEqual(request["params"]["auth"], {"token": "initial-token"})

    def test_plaintext_gateway_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                GatewayNode(
                    "ws://localhost:18789", self.identity, lambda _: None,
                    token_path=Path(root) / "token",
                )

    def test_gateway_url_cannot_contain_credentials_or_query(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            for url in ("wss://user:secret@gateway.example", "wss://gateway.example/?token=x"):
                with self.assertRaises(ValueError):
                    GatewayNode(url, self.identity, lambda _: None,
                                token_path=Path(root) / "token")

    def test_private_tcp_override_preserves_certificate_name(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            node = GatewayNode(
                "wss://gateway.example:19443/", self.identity, lambda _: None,
                token_path=Path(root) / "token", connect_host="192.168.1.10",
            )
            self.assertEqual(node.connect_host, "192.168.1.10")
            self.assertEqual(node.tls_name, "gateway.example")
            self.assertEqual(node.port, 19443)
            for invalid in ("8.8.8.8", "gateway.example", "127.0.0.1"):
                with self.assertRaises(ValueError):
                    GatewayNode("wss://gateway.example", self.identity, lambda _: None,
                                token_path=Path(root) / "token", connect_host=invalid)

    def test_device_token_storage_is_private(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            node = GatewayNode(
                "wss://gateway.example", self.identity, lambda _: None,
                token_path=Path(root) / "state" / "token",
            )
            node._store_token("secret-token")
            self.assertEqual(node._read_secret(node.token_path), "secret-token")
            self.assertEqual(node.token_path.stat().st_mode & 0o777, 0o600)

    def test_dangling_token_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            token = Path(root) / "token"
            token.symlink_to(Path(root) / "missing")
            node = GatewayNode("wss://gateway.example", self.identity, lambda _: None,
                               token_path=token)
            with self.assertRaises(PermissionError):
                node._read_secret(token)

    def test_invocation_uses_native_params_json_field(self) -> None:
        self.assertEqual(invoke_params({"paramsJSON": '{"action":"status"}'}), {"action": "status"})
        with self.assertRaises(ValueError):
            invoke_params({"paramsJSON": "[]"})


if __name__ == "__main__":
    unittest.main()
