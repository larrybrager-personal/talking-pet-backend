import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import main


class RequestIdBehaviorTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._auth_enabled = main.API_AUTH_ENABLED
        self._final_video_debug = main.ENABLE_FINAL_VIDEO_DEBUG
        main.API_AUTH_ENABLED = False
        main.ENABLE_FINAL_VIDEO_DEBUG = False
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        main.API_AUTH_ENABLED = self._auth_enabled
        main.ENABLE_FINAL_VIDEO_DEBUG = self._final_video_debug

    def test_health_includes_generated_request_id_header(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers.get("x-request-id"))

    def test_validation_error_body_includes_request_id(self):
        response = self.client.post(
            "/jobs_prompt_only",
            headers={"x-request-id": "corr-validation"},
            json={},
        )

        self.assertEqual(response.status_code, 422)
        payload = response.json()
        self.assertEqual(payload["requestId"], "corr-validation")
        self.assertIn("error", payload)
        self.assertIn("detail", payload)
        self.assertEqual(response.headers.get("x-request-id"), "corr-validation")

    def test_idempotent_replay_uses_current_request_id_in_body(self):
        with (
            patch("main._resolve_job_model", new_callable=AsyncMock) as mock_resolve,
            patch(
                "main.create_job_request_processing", new_callable=AsyncMock
            ) as mock_claim,
            patch(
                "main.await_existing_job_request", new_callable=AsyncMock
            ) as mock_existing,
            patch(
                "main.generate_video_from_prompt", new_callable=AsyncMock
            ) as mock_video,
        ):
            mock_resolve.return_value = (
                "wan-video/wan2.6-i2v-flash",
                {},
                {"seconds": 6, "resolution": "768p", "fps": None},
            )
            mock_claim.return_value = False
            mock_existing.return_value = {
                "video_url": "https://cached/video.mp4",
                "final_url": "https://cached/final.mp4",
                "requestId": "stale-request-id",
            }

            response = self.client.post(
                "/jobs_prompt_only",
                headers={"x-request-id": "corr-replay"},
                json={
                    "image_url": "https://example.com/pet.jpg",
                    "prompt": "A smiling pet",
                    "request_id": "11111111-1111-1111-1111-111111111111",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["requestId"], "corr-replay")
        self.assertEqual(response.headers.get("x-request-id"), "corr-replay")
        mock_video.assert_not_called()

    def test_success_payloads_include_request_id(self):
        resolve_response = self.client.post(
            "/resolve_model",
            headers={"x-request-id": "corr-resolve"},
            json={
                "seconds": 6,
                "resolution": "768p",
                "quality": "fast",
                "has_audio": False,
                "model_override": "bytedance/seedance-1-pro-fast",
            },
        )
        self.assertEqual(resolve_response.status_code, 200)
        self.assertEqual(resolve_response.json()["requestId"], "corr-resolve")

        with (
            patch("main._resolve_job_model", new_callable=AsyncMock) as mock_resolve,
            patch(
                "main.generate_video_from_prompt", new_callable=AsyncMock
            ) as mock_video,
            patch("main.fetch_binary", new_callable=AsyncMock) as mock_fetch,
            patch("main.supabase_upload", new_callable=AsyncMock) as mock_upload,
            patch("main.insert_pet_video", new_callable=AsyncMock),
            patch("main.prepare_video_for_upload_with_debug") as mock_prepare,
        ):
            mock_resolve.return_value = (
                "wan-video/wan2.6-i2v-flash",
                {},
                {"seconds": 6, "resolution": "768p", "fps": None},
            )
            mock_video.return_value = "https://example.com/video.mp4"
            mock_fetch.return_value = b"video-bytes"
            mock_prepare.return_value = (b"video-bytes", {"attempts": []})
            mock_upload.return_value = "https://example.com/final.mp4"

            response = self.client.post(
                "/jobs_prompt_only",
                headers={"x-request-id": "corr-job"},
                json={
                    "image_url": "https://example.com/pet.jpg",
                    "prompt": "A smiling pet",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["requestId"], "corr-job")
        self.assertEqual(response.headers.get("x-request-id"), "corr-job")


if __name__ == "__main__":
    unittest.main()
