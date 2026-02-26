import unittest
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
            patch("main._compress_video_bytes", side_effect=[b"x" * 20, b"x" * 20, b"x" * 20]),
        ):
            with self.assertRaises(HTTPException) as exc:
                main.prepare_video_for_upload(b"x" * 20)

        self.assertEqual(exc.exception.status_code, 400)
        self.assertIn("too large", exc.exception.detail)


if __name__ == "__main__":
    unittest.main()
