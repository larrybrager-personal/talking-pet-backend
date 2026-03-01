import asyncio
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

import main


class PrepareVideoForUploadTest(unittest.TestCase):
    def test_returns_original_when_already_within_limit(self):
        with patch("main.VIDEO_UPLOAD_TARGET_BYTES", 10):
            data = b"12345"
            self.assertEqual(main.prepare_video_for_upload(data), data)

    def test_compresses_until_within_limit(self):
        with (
            patch("main.VIDEO_UPLOAD_TARGET_BYTES", 10),
            patch(
                "main._compress_video_bytes",
                side_effect=[b"123456789012", b"1234567890"],
            ) as mock_compress,
        ):
            result = main.prepare_video_for_upload(b"x" * 20)

        self.assertEqual(result, b"1234567890")
        self.assertEqual(mock_compress.call_count, 2)

    def test_raises_when_still_too_large_after_attempts(self):
        with (
            patch("main.VIDEO_UPLOAD_TARGET_BYTES", 10),
            patch(
                "main._compress_video_bytes",
                side_effect=[b"x" * 20, b"x" * 20, b"x" * 20],
            ),
        ):
            with self.assertRaises(HTTPException) as exc:
                main.prepare_video_for_upload(b"x" * 20)

        self.assertEqual(exc.exception.status_code, 400)
        self.assertIn("too large", exc.exception.detail)


class GetFfmpegPathTest(unittest.TestCase):
    def setUp(self):
        main.get_ffmpeg_path.cache_clear()

    def test_prefers_imageio_ffmpeg_when_available(self):
        fake_module = SimpleNamespace(get_ffmpeg_exe=lambda: "/fake/ffmpeg")

        with (
            patch.object(main.importlib, "import_module", return_value=fake_module),
            patch.object(main.subprocess, "run") as mock_run,
        ):
            ffmpeg_path = main.get_ffmpeg_path()

        self.assertEqual(ffmpeg_path, "/fake/ffmpeg")
        mock_run.assert_called_once_with(
            ["/fake/ffmpeg", "-version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_falls_back_to_path_when_imageio_import_fails(self):
        with (
            patch.object(
                main.importlib, "import_module", side_effect=ImportError("missing")
            ),
            patch.object(main.shutil, "which", return_value="/usr/bin/ffmpeg"),
            patch.object(main.subprocess, "run") as mock_run,
        ):
            ffmpeg_path = main.get_ffmpeg_path()

        self.assertEqual(ffmpeg_path, "/usr/bin/ffmpeg")
        mock_run.assert_called_once_with(
            ["/usr/bin/ffmpeg", "-version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_falls_back_to_path_on_unexpected_import_exception(self):
        with (
            patch.object(
                main.importlib,
                "import_module",
                side_effect=Exception("No module named 'pkg_resources'"),
            ),
            patch.object(main.shutil, "which", return_value="/usr/bin/ffmpeg"),
            patch.object(main.subprocess, "run") as mock_run,
            patch.object(main.logger, "warning") as mock_warning,
        ):
            ffmpeg_path = main.get_ffmpeg_path()

        self.assertEqual(ffmpeg_path, "/usr/bin/ffmpeg")
        mock_run.assert_called_once_with(
            ["/usr/bin/ffmpeg", "-version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertTrue(mock_warning.called)
        warning_message = mock_warning.call_args[0][0]
        self.assertIn("setuptools", warning_message)

    def test_raises_http_500_when_imageio_and_path_ffmpeg_missing(self):
        with (
            patch.object(
                main.importlib, "import_module", side_effect=ImportError("missing")
            ),
            patch.object(main.shutil, "which", return_value=None),
        ):
            with self.assertRaises(HTTPException) as exc:
                main.get_ffmpeg_path()

        self.assertEqual(exc.exception.status_code, 500)
        self.assertEqual(exc.exception.detail, "ffmpeg not available in runtime")


class FfmpegSmokeCheckTest(unittest.TestCase):
    def test_logs_warning_when_ffmpeg_unavailable(self):
        with (
            patch(
                "main.get_ffmpeg_path",
                side_effect=HTTPException(500, "ffmpeg not available in runtime"),
            ),
            patch.object(main.logger, "warning") as mock_warning,
        ):
            main.run_ffmpeg_runtime_smoke_check()

        self.assertTrue(mock_warning.called)

    def test_logs_info_when_ffmpeg_available(self):
        with (
            patch("main.get_ffmpeg_path", return_value="/usr/bin/ffmpeg"),
            patch.object(main.logger, "info") as mock_info,
        ):
            main.run_ffmpeg_runtime_smoke_check()

        self.assertTrue(mock_info.called)

    def test_logs_warning_when_ffmpeg_lookup_raises_unexpected_error(self):
        with (
            patch(
                "main.get_ffmpeg_path", side_effect=PermissionError("not executable")
            ),
            patch.object(main.logger, "warning") as mock_warning,
        ):
            main.run_ffmpeg_runtime_smoke_check()

        self.assertTrue(mock_warning.called)

    def test_returns_path_when_ffmpeg_available(self):
        try:
            ffmpeg_path = main.get_ffmpeg_path()
        except HTTPException as exc:
            if exc.status_code == 500 and "ffmpeg not available" in str(exc.detail):
                self.skipTest("ffmpeg not available in test runtime")
            raise

        self.assertTrue(isinstance(ffmpeg_path, str) and len(ffmpeg_path) > 0)


class MuxVideoAudioTest(unittest.TestCase):
    class _FakeResponse:
        def __init__(self, content: bytes):
            self.content = content

        def raise_for_status(self):
            return None

    class _FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str):
            if url.endswith(".mp3"):
                return MuxVideoAudioTest._FakeResponse(b"audio-bytes")
            return MuxVideoAudioTest._FakeResponse(b"video-bytes")

    def test_mux_maps_called_process_error_to_http_500(self):
        async def run_test():
            with (
                patch("main.httpx.AsyncClient", return_value=self._FakeAsyncClient()),
                patch("main.get_ffmpeg_path", return_value="/usr/bin/ffmpeg"),
                patch(
                    "main.subprocess.run",
                    side_effect=subprocess.CalledProcessError(
                        1,
                        ["/usr/bin/ffmpeg"],
                        stderr="mux failed",
                    ),
                ),
            ):
                with self.assertRaises(HTTPException) as exc:
                    await main.mux_video_audio(
                        "https://example.com/video.mp4", "https://example.com/audio.mp3"
                    )

            self.assertEqual(exc.exception.status_code, 500)
            self.assertEqual(exc.exception.detail, "ffmpeg mux failed")

        asyncio.run(run_test())

    def test_mux_maps_missing_ffmpeg_to_http_500(self):
        async def run_test():
            with (
                patch("main.httpx.AsyncClient", return_value=self._FakeAsyncClient()),
                patch("main.get_ffmpeg_path", side_effect=FileNotFoundError("missing")),
            ):
                with self.assertRaises(HTTPException) as exc:
                    await main.mux_video_audio(
                        "https://example.com/video.mp4", "https://example.com/audio.mp3"
                    )

            self.assertEqual(exc.exception.status_code, 500)
            self.assertEqual(exc.exception.detail, "ffmpeg not available in runtime")

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
