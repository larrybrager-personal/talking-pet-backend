import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

import main


class _StreamResponse:
    def __init__(
        self,
        *,
        url: str,
        status_code: int,
        headers: dict[str, str] | None = None,
        body: bytes = b""
    ):
        self.url = url
        self.status_code = status_code
        self.headers = headers or {}
        self._body = body
        self.is_redirect = status_code in {301, 302, 303, 307, 308}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise HTTPException(self.status_code, "upstream error")

    async def aiter_bytes(self):
        if self._body:
            yield self._body


class _FetchClient:
    def __init__(self, responses):
        self._responses = iter(responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, method, url):
        return next(self._responses)


class _HeadResponse:
    def __init__(
        self, *, url: str, status_code: int, headers: dict[str, str] | None = None
    ):
        self.url = url
        self.status_code = status_code
        self.headers = headers or {}
        self.is_redirect = status_code in {301, 302, 303, 307, 308}


class _HeadClient:
    def __init__(self, head_responses, get_response):
        self._head_responses = iter(head_responses)
        self._get_response = get_response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def head(self, _url):
        return next(self._head_responses)

    async def get(self, _url, headers=None):
        return self._get_response


class RedirectValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_binary_revalidates_redirect_targets(self):
        responses = [
            _StreamResponse(
                url="https://public.example/start",
                status_code=302,
                headers={"location": "http://169.254.169.254/latest/meta-data"},
            ),
        ]

        validate = Mock()

        def validate_side_effect(url, *, allow_private=False):
            if "169.254.169.254" in url:
                raise HTTPException(400, "URL host is not publicly routable.")

        validate.side_effect = validate_side_effect

        with patch("main._validate_outbound_url", validate), patch(
            "main.httpx.AsyncClient", return_value=_FetchClient(responses)
        ):
            with self.assertRaises(HTTPException) as exc:
                await main.fetch_binary("https://public.example/start")

        self.assertEqual(exc.exception.status_code, 400)
        called_urls = [call.args[0] for call in validate.call_args_list]
        self.assertEqual(
            called_urls,
            [
                "https://public.example/start",
                "http://169.254.169.254/latest/meta-data",
            ],
        )

    async def test_head_info_revalidates_redirect_targets(self):
        head_responses = [
            _HeadResponse(
                url="https://public.example/start",
                status_code=302,
                headers={"location": "http://127.0.0.1/internal"},
            ),
        ]
        validate = Mock()

        def validate_side_effect(url, *, allow_private=False):
            if "127.0.0.1" in url:
                raise HTTPException(400, "URL host is not publicly routable.")

        validate.side_effect = validate_side_effect

        with patch("main._validate_outbound_url", validate), patch(
            "main.httpx.AsyncClient",
            return_value=_HeadClient(
                head_responses,
                _HeadResponse(url="https://public.example/start", status_code=200),
            ),
        ):
            with self.assertRaises(HTTPException) as exc:
                await main.head_info("https://public.example/start")

        self.assertEqual(exc.exception.status_code, 400)
        called_urls = [call.args[0] for call in validate.call_args_list]
        self.assertEqual(
            called_urls,
            [
                "https://public.example/start",
                "http://127.0.0.1/internal",
            ],
        )


if __name__ == "__main__":
    unittest.main()
