import unittest

from fastapi import HTTPException

from main import UserContext, resolve_user_storage_prefix, build_storage_key


class StorageHelpersTestCase(unittest.TestCase):
    def test_anonymous_prefix_when_context_missing(self):
        self.assertEqual(resolve_user_storage_prefix(None), "anonymous")

    def test_valid_uuid_prefix_is_normalized(self):
        context = UserContext(id="00000000-0000-0000-0000-000000000000")
        self.assertEqual(
            resolve_user_storage_prefix(context),
            "users/00000000-0000-0000-0000-000000000000",
        )

    def test_invalid_uuid_raises_http_exception(self):
        with self.assertRaises(HTTPException) as exc:
            resolve_user_storage_prefix(UserContext(id="not-a-uuid"))
        self.assertEqual(exc.exception.status_code, 400)

    def test_build_storage_key_scopes_to_prefix(self):
        key = build_storage_key("users/00000000-0000-0000-0000-000000000000", "videos", "mp4")
        self.assertTrue(key.startswith("users/00000000-0000-0000-0000-000000000000/videos/"))
        self.assertTrue(key.endswith(".mp4"))


if __name__ == "__main__":
    unittest.main()
