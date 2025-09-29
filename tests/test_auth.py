import unittest

from fastapi import HTTPException
from starlette.requests import Request

import main


class RequireAuthTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._original_enabled = main.API_AUTH_ENABLED
        self._original_token = main.API_AUTH_TOKEN

    def tearDown(self) -> None:
        main.API_AUTH_ENABLED = self._original_enabled
        main.API_AUTH_TOKEN = self._original_token

    @staticmethod
    def _make_request(headers: dict[str, str] | None = None) -> Request:
        scope = {
            "type": "http",
            "headers": [],
        }
        if headers:
            scope["headers"] = [
                (key.lower().encode("latin-1"), value.encode("latin-1"))
                for key, value in headers.items()
            ]
        return Request(scope)

    async def test_auth_disabled_allows_request(self):
        main.API_AUTH_ENABLED = False
        main.API_AUTH_TOKEN = ""

        request = self._make_request()
        await main.require_auth(request)

    async def test_enabled_without_token_raises_server_error(self):
        main.API_AUTH_ENABLED = True
        main.API_AUTH_TOKEN = ""

        request = self._make_request()
        with self.assertRaises(HTTPException) as exc:
            await main.require_auth(request)
        self.assertEqual(exc.exception.status_code, 500)

    async def test_missing_authorization_header_is_rejected(self):
        main.API_AUTH_ENABLED = True
        main.API_AUTH_TOKEN = "secret"

        request = self._make_request()
        with self.assertRaises(HTTPException) as exc:
            await main.require_auth(request)
        self.assertEqual(exc.exception.status_code, 401)

    async def test_invalid_token_is_rejected(self):
        main.API_AUTH_ENABLED = True
        main.API_AUTH_TOKEN = "secret"

        request = self._make_request({"Authorization": "Bearer nope"})
        with self.assertRaises(HTTPException) as exc:
            await main.require_auth(request)
        self.assertEqual(exc.exception.status_code, 403)

    async def test_valid_token_is_accepted(self):
        main.API_AUTH_ENABLED = True
        main.API_AUTH_TOKEN = "secret"

        request = self._make_request({"Authorization": "Bearer secret"})
        await main.require_auth(request)


if __name__ == "__main__":
    unittest.main()
