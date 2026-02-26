import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import main


class InsertPetVideoHelperTest(unittest.IsolatedAsyncioTestCase):
    async def test_insert_pet_video_posts_expected_payload(self):
        created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        response_mock = AsyncMock()
        response_mock.status_code = 201
        response_mock.text = ""

        client_mock = AsyncMock()
        client_mock.post = AsyncMock(return_value=response_mock)

        with (
            patch("main.SUPABASE_URL", "https://supabase.test"),
            patch("main.SUPABASE_SERVICE_ROLE", "service-role"),
            patch("main.httpx.AsyncClient") as async_client_cls,
        ):
            async_client_cls.return_value.__aenter__.return_value = client_mock

            await main.insert_pet_video(
                user_id="user-123",
                video_url="https://public.final/video.mp4",
                image_url="https://example.com/pet.jpg",
                script="Hello!",
                prompt="Wave hello",
                voice_id="voice-id",
                resolution="768p",
                duration=6,
                model="wan-video/wan-2.2-s2v",
                created_at=created_at,
            )

        client_mock.post.assert_awaited_once()
        call_kwargs = client_mock.post.await_args.kwargs
        self.assertEqual(
            call_kwargs["headers"],
            {
                "Authorization": "Bearer service-role",
                "apikey": "service-role",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
        )
        self.assertEqual(
            call_kwargs["json"],
            {
                "user_id": "user-123",
                "video_url": "https://public.final/video.mp4",
                "image_url": "https://example.com/pet.jpg",
                "script": "Hello!",
                "prompt": "Wave hello",
                "voice_id": "voice-id",
                "resolution": "768p",
                "duration": 6,
                "model": "wan-video/wan-2.2-s2v",
                "created_at": created_at.isoformat(),
            },
        )


class HandlerMetadataTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_job_with_prompt_records_metadata(self):
        req = main.JobPromptOnly(
            image_url="https://example.com/pet.jpg",
            prompt="Say hi",
            seconds=6,
            resolution="768p",
            model=None,
            user_context=main.UserContext(id="00000000-0000-0000-0000-000000000000"),
        )

        with (
            patch(
                "main.generate_video_from_prompt", new_callable=AsyncMock
            ) as mock_generate,
            patch("main.fetch_binary", new_callable=AsyncMock) as mock_fetch,
            patch("main.supabase_upload", new_callable=AsyncMock) as mock_upload,
            patch("main.prepare_video_for_upload", return_value=b"compressed-video"),
            patch("main.build_storage_key", return_value="videos/final.mp4"),
            patch("main.insert_pet_video", new_callable=AsyncMock) as mock_insert,
            patch(
                "main.collect_video_delivery_debug", new_callable=AsyncMock
            ) as mock_debug,
        ):
            mock_generate.return_value = "https://model/video.mp4"
            mock_fetch.return_value = b"video-bytes"
            mock_upload.return_value = "https://public.final/video.mp4"

            mock_debug.return_value = {"head_status": 200, "content_length": 100}
            result = await main.create_job_with_prompt(req)

        mock_insert.assert_awaited_once()
        insert_kwargs = mock_insert.await_args.kwargs
        self.assertEqual(
            insert_kwargs,
            {
                "user_id": "00000000-0000-0000-0000-000000000000",
                "video_url": "https://public.final/video.mp4",
                "image_url": "https://example.com/pet.jpg",
                "script": None,
                "prompt": "Say hi",
                "voice_id": None,
                "resolution": "720p",
                "duration": 5,
                "model": main.PROMPT_ONLY_FALLBACK_MODEL,
            },
        )
        self.assertEqual(
            result,
            {
                "video_url": "https://model/video.mp4",
                "final_url": "https://public.final/video.mp4",
            },
        )
        upload_args = mock_upload.await_args.args
        self.assertEqual(upload_args[0], b"compressed-video")

    async def test_create_job_with_prompt_and_tts_records_metadata(self):
        req = main.JobPromptTTS(
            image_url="https://example.com/pet.jpg",
            prompt="Say hi",
            text="Hello!",
            voice_id="voice-123",
            seconds=6,
            resolution="768p",
            model=None,
            user_context=main.UserContext(id="11111111-1111-1111-1111-111111111111"),
        )

        with (
            patch("main.elevenlabs_tts_bytes", new_callable=AsyncMock) as mock_tts,
            patch(
                "main.generate_video_from_prompt", new_callable=AsyncMock
            ) as mock_generate,
            patch("main.mux_video_audio", new_callable=AsyncMock) as mock_mux,
            patch("main.fetch_binary", new_callable=AsyncMock) as mock_fetch,
            patch(
                "main.build_storage_key",
                side_effect=["audio/file.mp3", "videos/final.mp4"],
            ),
            patch(
                "main.supabase_upload",
                new_callable=AsyncMock,
            ) as mock_upload,
            patch("main.prepare_video_for_upload", return_value=b"compressed-video"),
            patch("main.insert_pet_video", new_callable=AsyncMock) as mock_insert,
            patch(
                "main.collect_video_delivery_debug", new_callable=AsyncMock
            ) as mock_debug,
        ):
            mock_tts.return_value = b"mp3"
            mock_generate.return_value = "https://model/video.mp4"
            mock_mux.return_value = b"muxed"
            mock_fetch.return_value = b"video"
            mock_upload.side_effect = [
                "https://public.audio/audio.mp3",
                "https://public.final/video.mp4",
            ]

            mock_debug.return_value = {"head_status": 200, "content_length": 100}
            result = await main.create_job_with_prompt_and_tts(req)

        mock_insert.assert_awaited_once()
        insert_kwargs = mock_insert.await_args.kwargs
        self.assertEqual(
            insert_kwargs,
            {
                "user_id": "11111111-1111-1111-1111-111111111111",
                "video_url": "https://public.final/video.mp4",
                "image_url": "https://example.com/pet.jpg",
                "script": "Hello!",
                "prompt": "Say hi",
                "voice_id": "voice-123",
                "resolution": "720p",
                "duration": 5,
                "model": main.DEFAULT_MODEL,
            },
        )
        self.assertEqual(
            result,
            {
                "audio_url": "https://public.audio/audio.mp3",
                "video_url": "https://model/video.mp4",
                "final_url": "https://public.final/video.mp4",
            },
        )
        self.assertEqual(mock_upload.await_args_list[1].args[0], b"compressed-video")


class ModelParamsAllowlistTest(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_model_params_are_ignored(self):
        req = main.JobPromptOnly(
            image_url="https://example.com/pet.jpg",
            prompt="Say hi",
            seconds=6,
            resolution="768p",
            model_override="wan-video/wan2.6-i2v-flash",
            model_params={"fps": 30, "unknown": "ignore-me"},
            user_context=main.UserContext(id="00000000-0000-0000-0000-000000000000"),
        )

        with (
            patch(
                "main.generate_video_from_prompt", new_callable=AsyncMock
            ) as mock_generate,
            patch("main.fetch_binary", new_callable=AsyncMock) as mock_fetch,
            patch("main.supabase_upload", new_callable=AsyncMock) as mock_upload,
            patch("main.prepare_video_for_upload", return_value=b"compressed-video"),
            patch("main.build_storage_key", return_value="videos/final.mp4"),
            patch("main.insert_pet_video", new_callable=AsyncMock),
            patch(
                "main.collect_video_delivery_debug", new_callable=AsyncMock
            ) as mock_debug,
        ):
            mock_generate.return_value = "https://model/video.mp4"
            mock_fetch.return_value = b"video-bytes"
            mock_upload.return_value = "https://public.final/video.mp4"

            mock_debug.return_value = {"head_status": 200, "content_length": 100}
            await main.create_job_with_prompt(req)

        generate_kwargs = mock_generate.await_args.kwargs
        self.assertEqual(generate_kwargs["input_params"], {"fps": 30})


class FinalVideoDebugTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_job_with_prompt_raises_when_final_url_unreachable(self):
        req = main.JobPromptOnly(
            image_url="https://example.com/pet.jpg",
            prompt="Say hi",
            user_context=main.UserContext(id="00000000-0000-0000-0000-000000000000"),
        )

        with (
            patch(
                "main.generate_video_from_prompt", new_callable=AsyncMock
            ) as mock_generate,
            patch("main.fetch_binary", new_callable=AsyncMock) as mock_fetch,
            patch("main.supabase_upload", new_callable=AsyncMock) as mock_upload,
            patch("main.prepare_video_for_upload", return_value=b"compressed-video"),
            patch("main.build_storage_key", return_value="videos/final.mp4"),
            patch("main.insert_pet_video", new_callable=AsyncMock),
            patch(
                "main.collect_video_delivery_debug", new_callable=AsyncMock
            ) as mock_debug,
            patch("main.supabase_delete", new_callable=AsyncMock) as mock_delete,
        ):
            mock_generate.return_value = "https://model/video.mp4"
            mock_fetch.return_value = b"video-bytes"
            mock_upload.return_value = "https://public.final/video.mp4"
            mock_debug.return_value = {"head_status": 404, "content_length": 0}

            with self.assertRaises(main.HTTPException) as exc:
                await main.create_job_with_prompt(req)

        self.assertEqual(exc.exception.status_code, 502)
        mock_delete.assert_awaited_once_with("videos/final.mp4")

    async def test_debug_final_video_returns_probe_data(self):
        req = main.FinalVideoDebugRequest(url="https://public.final/video.mp4")

        with (
            patch(
                "main.collect_video_delivery_debug", new_callable=AsyncMock
            ) as mock_collect,
            patch("main.fetch_binary", new_callable=AsyncMock) as mock_fetch,
            patch("main.inspect_video_bytes", return_value={"is_valid_mp4": True}),
        ):
            mock_collect.return_value = {"head_status": 200, "content_length": 111}
            mock_fetch.return_value = b"abc"

            result = await main.debug_final_video(req)

        self.assertEqual(result["head_status"], 200)
        self.assertEqual(result["downloaded_bytes"], 3)
        self.assertEqual(result["probe"], {"is_valid_mp4": True})


if __name__ == "__main__":
    unittest.main()
