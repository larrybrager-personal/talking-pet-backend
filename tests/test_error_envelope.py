import importlib
import os
import unittest

from fastapi.testclient import TestClient

import main


class ErrorEnvelopeAndHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_auth_enabled = os.environ.get("API_AUTH_ENABLED")
        self._original_auth_token = os.environ.get("API_AUTH_TOKEN")

    def tearDown(self) -> None:
        if self._original_auth_enabled is None:
            os.environ.pop("API_AUTH_ENABLED", None)
        else:
            os.environ["API_AUTH_ENABLED"] = self._original_auth_enabled

        if self._original_auth_token is None:
            os.environ.pop("API_AUTH_TOKEN", None)
        else:
            os.environ["API_AUTH_TOKEN"] = self._original_auth_token

        importlib.reload(main)

    def test_health_is_public_when_auth_enabled(self):
        os.environ["API_AUTH_ENABLED"] = "true"
        os.environ["API_AUTH_TOKEN"] = "secret-token"
        importlib.reload(main)

        client = TestClient(main.app)
        response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})

    def test_http_exception_error_includes_error_and_detail(self):
        os.environ["API_AUTH_ENABLED"] = "true"
        os.environ["API_AUTH_TOKEN"] = "secret-token"
        importlib.reload(main)

        client = TestClient(main.app)
        response = client.get("/models")

        payload = response.json()
        self.assertEqual(response.status_code, 401)
        self.assertIn("error", payload)
        self.assertIn("detail", payload)
        self.assertEqual(payload.get("status"), 401)
        self.assertEqual(payload["detail"], "Missing Authorization header")

    def test_unknown_route_uses_stable_error_envelope(self):
        os.environ["API_AUTH_ENABLED"] = "false"
        importlib.reload(main)

        client = TestClient(main.app)
        response = client.get("/does-not-exist")

        payload = response.json()
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", payload)
        self.assertIn("detail", payload)
        self.assertEqual(payload.get("status"), 404)
        self.assertEqual(payload["detail"], "Not Found")

    def test_method_not_allowed_uses_stable_error_envelope(self):
        os.environ["API_AUTH_ENABLED"] = "false"
        importlib.reload(main)

        client = TestClient(main.app)
        response = client.post("/health")

        payload = response.json()
        self.assertEqual(response.status_code, 405)
        self.assertIn("error", payload)
        self.assertIn("detail", payload)
        self.assertEqual(payload.get("status"), 405)
        self.assertEqual(payload["detail"], "Method Not Allowed")
        self.assertEqual(response.headers.get("allow"), "GET")

    def test_resolve_model_validation_error_includes_error_and_detail(self):
        os.environ["API_AUTH_ENABLED"] = "false"
        importlib.reload(main)

        client = TestClient(main.app)
        response = client.post(
            "/resolve_model",
            json={"seconds": "bad-value"},
        )

        payload = response.json()
        self.assertEqual(response.status_code, 422)
        self.assertIn("error", payload)
        self.assertIn("detail", payload)
        self.assertEqual(payload.get("status"), 422)
        self.assertIsInstance(payload["detail"], list)


if __name__ == "__main__":
    unittest.main()
