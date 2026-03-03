import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import main
from fastapi import HTTPException


class IdempotencyBehaviorTest(unittest.IsolatedAsyncioTestCase):
    async def test_prompt_only_invalid_image_url_fails_before_claiming_request_id(self):
        req = main.JobPromptOnly(
            image_url="file:///tmp/pet.jpg",
            prompt="Say hi",
            request_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        )

        with patch(
            "main.create_job_request_processing", new_callable=AsyncMock
        ) as mock_create_processing:
            with self.assertRaises(HTTPException) as ctx:
                await main.create_job_with_prompt(req)

        self.assertEqual(ctx.exception.status_code, 400)
        mock_create_processing.assert_not_awaited()

    async def test_prompt_only_invalid_model_fails_before_claiming_request_id(self):
        req = main.JobPromptOnly(
            image_url="https://example.com/pet.jpg",
            prompt="Say hi",
            model="wan-video/wan-2.2-s2v",
            request_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        )

        with patch(
            "main.create_job_request_processing", new_callable=AsyncMock
        ) as mock_create_processing:
            with self.assertRaises(HTTPException) as ctx:
                await main.create_job_with_prompt(req)

        self.assertIn(ctx.exception.status_code, (400, 403))
        mock_create_processing.assert_not_awaited()

    async def test_prompt_only_returns_cached_succeeded_response_without_regenerating(
        self,
    ):
        req = main.JobPromptOnly(
            image_url="https://example.com/pet.jpg",
            prompt="Say hi",
            request_id="11111111-1111-1111-1111-111111111111",
        )
        cached = {
            "video_url": "https://cached/model.mp4",
            "final_url": "https://cached/final.mp4",
        }

        with (
            patch(
                "main.create_job_request_processing", new_callable=AsyncMock
            ) as mock_create_processing,
            patch(
                "main.await_existing_job_request", new_callable=AsyncMock
            ) as mock_await_existing,
            patch(
                "main.generate_video_from_prompt", new_callable=AsyncMock
            ) as mock_generate,
            patch("main.fetch_binary", new_callable=AsyncMock) as mock_fetch,
            patch("main.elevenlabs_tts_bytes", new_callable=AsyncMock) as mock_tts,
        ):
            mock_create_processing.return_value = False
            mock_await_existing.return_value = cached

            result = await main.create_job_with_prompt(req)

        self.assertEqual(result, cached)
        mock_generate.assert_not_called()
        mock_fetch.assert_not_called()
        mock_tts.assert_not_called()

    async def test_prompt_only_owner_updates_succeeded_with_response_payload(self):
        req = main.JobPromptOnly(
            image_url="https://example.com/pet.jpg",
            prompt="Say hi",
            request_id="22222222-2222-2222-2222-222222222222",
            user_context=main.UserContext(id="00000000-0000-0000-0000-000000000000"),
        )

        with (
            patch(
                "main.create_job_request_processing", new_callable=AsyncMock
            ) as mock_create_processing,
            patch("main._resolve_job_model", new_callable=AsyncMock) as mock_resolve,
            patch(
                "main.generate_video_from_prompt", new_callable=AsyncMock
            ) as mock_generate,
            patch("main.fetch_binary", new_callable=AsyncMock) as mock_fetch,
            patch(
                "main.prepare_video_for_upload_with_debug",
                return_value=(b"compressed", {"meets_target": True}),
            ),
            patch("main.build_storage_key", return_value="videos/final.mp4"),
            patch("main.supabase_upload", new_callable=AsyncMock) as mock_upload,
            patch("main.insert_pet_video", new_callable=AsyncMock),
            patch(
                "main.collect_video_delivery_debug", new_callable=AsyncMock
            ) as mock_debug,
            patch("main.update_job_request", new_callable=AsyncMock) as mock_update,
        ):
            mock_create_processing.return_value = True
            mock_resolve.return_value = (
                "wan-video/wan2.6-i2v-flash",
                {},
                {"seconds": 5, "resolution": "720p", "fps": None},
            )
            mock_generate.return_value = "https://model/video.mp4"
            mock_fetch.return_value = b"video-bytes"
            mock_upload.return_value = "https://public/final.mp4"
            mock_debug.return_value = {"head_status": 200, "content_length": 100}

            result = await main.create_job_with_prompt(req)

        self.assertEqual(
            result,
            {
                "video_url": "https://model/video.mp4",
                "final_url": "https://public/final.mp4",
            },
        )
        mock_update.assert_awaited_once_with(
            "22222222-2222-2222-2222-222222222222",
            "succeeded",
            response_payload={
                "video_url": "https://model/video.mp4",
                "final_url": "https://public/final.mp4",
            },
            error=None,
        )

    async def test_processing_duplicate_polls_then_returns_succeeded_response(self):
        request_id = "33333333-3333-3333-3333-333333333333"
        with (
            patch("main.get_job_request", new_callable=AsyncMock) as mock_get,
            patch("main.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            patch("main.IDEMPOTENCY_POLL_INTERVAL_SEC", 0.01),
            patch("main.IDEMPOTENCY_MAX_WAIT_SEC", 0.1),
        ):
            mock_get.side_effect = [
                {"status": "processing"},
                {
                    "status": "succeeded",
                    "response_payload": {
                        "audio_url": "https://public/audio.mp3",
                        "video_url": "https://public/video.mp4",
                        "final_url": "https://public/final.mp4",
                    },
                },
            ]

            result = await main.await_existing_job_request(request_id)

        self.assertEqual(
            result,
            {
                "audio_url": "https://public/audio.mp3",
                "video_url": "https://public/video.mp4",
                "final_url": "https://public/final.mp4",
            },
        )
        mock_sleep.assert_awaited_once()

    async def test_success_response_is_not_masked_by_idempotency_write_failure(self):
        req = main.JobPromptOnly(
            image_url="https://example.com/pet.jpg",
            prompt="Say hi",
            request_id="44444444-4444-4444-4444-444444444444",
            user_context=main.UserContext(id="00000000-0000-0000-0000-000000000000"),
        )

        with (
            patch(
                "main.create_job_request_processing", new_callable=AsyncMock
            ) as mock_create_processing,
            patch("main._resolve_job_model", new_callable=AsyncMock) as mock_resolve,
            patch(
                "main.generate_video_from_prompt", new_callable=AsyncMock
            ) as mock_generate,
            patch("main.fetch_binary", new_callable=AsyncMock) as mock_fetch,
            patch(
                "main.prepare_video_for_upload_with_debug",
                return_value=(b"compressed", {"meets_target": True}),
            ),
            patch("main.build_storage_key", return_value="videos/final.mp4"),
            patch("main.supabase_upload", new_callable=AsyncMock) as mock_upload,
            patch("main.insert_pet_video", new_callable=AsyncMock),
            patch(
                "main.collect_video_delivery_debug", new_callable=AsyncMock
            ) as mock_debug,
            patch(
                "main.update_job_request",
                new_callable=AsyncMock,
                side_effect=HTTPException(500, "idempotency write failed"),
            ),
        ):
            mock_create_processing.return_value = True
            mock_resolve.return_value = (
                "wan-video/wan2.6-i2v-flash",
                {},
                {"seconds": 5, "resolution": "720p", "fps": None},
            )
            mock_generate.return_value = "https://model/video.mp4"
            mock_fetch.return_value = b"video-bytes"
            mock_upload.return_value = "https://public/final.mp4"
            mock_debug.return_value = {"head_status": 200, "content_length": 100}

            result = await main.create_job_with_prompt(req)

        self.assertEqual(
            result,
            {
                "video_url": "https://model/video.mp4",
                "final_url": "https://public/final.mp4",
            },
        )

    async def test_failure_response_is_not_masked_by_idempotency_write_failure(self):
        req = main.JobPromptOnly(
            image_url="https://example.com/pet.jpg",
            prompt="Say hi",
            request_id="55555555-5555-5555-5555-555555555555",
        )

        with (
            patch(
                "main.create_job_request_processing", new_callable=AsyncMock
            ) as mock_create_processing,
            patch("main._resolve_job_model", new_callable=AsyncMock) as mock_resolve,
            patch(
                "main.generate_video_from_prompt",
                new_callable=AsyncMock,
                side_effect=HTTPException(400, "provider rejected request"),
            ),
            patch(
                "main.update_job_request",
                new_callable=AsyncMock,
                side_effect=HTTPException(500, "idempotency write failed"),
            ),
        ):
            mock_create_processing.return_value = True
            mock_resolve.return_value = (
                "wan-video/wan2.6-i2v-flash",
                {},
                {"seconds": 5, "resolution": "720p", "fps": None},
            )

            with self.assertRaises(HTTPException) as exc:
                await main.create_job_with_prompt(req)

        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(exc.exception.detail, "provider rejected request")

    async def test_create_processing_rejects_cross_endpoint_conflict(self):
        with (
            patch("main.SUPABASE_URL", "https://supabase.local"),
            patch("main.SUPABASE_SERVICE_ROLE", "service-role"),
            patch("main.get_job_request", new_callable=AsyncMock) as mock_get,
        ):
            post_response = MagicMock()
            post_response.status_code = 409

            mock_client = AsyncMock()
            mock_client.post.return_value = post_response

            client_cm = AsyncMock()
            client_cm.__aenter__.return_value = mock_client
            client_cm.__aexit__.return_value = False

            with patch("main.httpx.AsyncClient", return_value=client_cm):
                mock_get.return_value = {
                    "request_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                    "endpoint": "/jobs_prompt_tts",
                    "user_id": "user-2",
                    "status": "succeeded",
                }

                with self.assertRaises(HTTPException) as ctx:
                    await main.create_job_request_processing(
                        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                        "user-1",
                        "/jobs_prompt_only",
                    )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("different endpoint or user scope", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
