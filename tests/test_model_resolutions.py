import unittest

from fastapi.testclient import TestClient

import main


class BuildModelPayloadResolutionTestCase(unittest.TestCase):
    def test_wan26_flash_respects_resolution(self):
        payload = main.build_model_payload(
            "wan-video/wan2.6-i2v-flash",
            image_url="https://example.com/image.jpg",
            prompt="hello",
            seconds=6,
            resolution="1080p",
        )

        self.assertEqual(payload["input"]["resolution"], "1080p")

    def test_hailuo23_passes_1080p_resolution(self):
        payload = main.build_model_payload(
            "minimax/hailuo-2.3",
            image_url="https://example.com/image.jpg",
            prompt="hello",
            seconds=6,
            resolution="1080p",
        )

        self.assertEqual(payload["input"]["resolution"], "1080p")

    def test_seedance_pro_fast_passes_1080p_resolution(self):
        payload = main.build_model_payload(
            "bytedance/seedance-1-pro-fast",
            image_url="https://example.com/image.jpg",
            prompt="hello",
            seconds=6,
            resolution="1080p",
        )

        self.assertEqual(payload["input"]["resolution"], "1080p")

    def test_kling_switches_to_pro_mode_for_1080p(self):
        payload = main.build_model_payload(
            "kwaivgi/kling-v2.6",
            image_url="https://example.com/image.jpg",
            prompt="hello",
            seconds=6,
            resolution="1080p",
        )

        self.assertEqual(payload["input"]["mode"], "pro")
        self.assertEqual(payload["input"]["aspect_ratio"], "16:9")

    def test_kling_uses_standard_mode_for_non_1080p(self):
        payload = main.build_model_payload(
            "kwaivgi/kling-v2.6",
            image_url="https://example.com/image.jpg",
            prompt="hello",
            seconds=6,
            resolution="768p",
        )

        self.assertEqual(payload["input"]["mode"], "standard")
        self.assertEqual(payload["input"]["aspect_ratio"], "1:1")


class ModelNormalizationTestCase(unittest.TestCase):
    def test_legacy_slugs_are_normalized(self):
        self.assertEqual(
            main.normalize_video_model("minimax/hailuo-02"),
            "minimax/hailuo-2.3",
        )
        self.assertEqual(
            main.normalize_video_model("kwaivgi/kling-v2.1"),
            "kwaivgi/kling-v2.6",
        )
        self.assertEqual(
            main.normalize_video_model("bytedance/seedance-1-lite"),
            "bytedance/seedance-1-pro-fast",
        )
        self.assertEqual(
            main.normalize_video_model("wan-video/wan-2.1"),
            "wan-video/wan2.6-i2v-flash",
        )

    def test_unknown_slug_falls_back_to_fast_default(self):
        self.assertEqual(
            main.normalize_video_model("unknown/model"),
            "wan-video/wan2.6-i2v-flash",
        )

    def test_default_routing_is_fast(self):
        self.assertEqual(main.get_default_video_model(), "wan-video/wan2.6-i2v-flash")


class ModelsEndpointResolutionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._auth_enabled = main.API_AUTH_ENABLED
        main.API_AUTH_ENABLED = False
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        main.API_AUTH_ENABLED = self._auth_enabled

    def test_supported_models_expose_resolutions_and_tiers(self):
        response = self.client.get("/models")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        wan26_fast = payload["supported_models"]["wan-video/wan2.6-i2v-flash"]
        wan22 = payload["supported_models"]["wan-video/wan-2.2-s2v"]
        hailuo = payload["supported_models"]["minimax/hailuo-2.3"]
        kling = payload["supported_models"]["kwaivgi/kling-v2.6"]
        seedance = payload["supported_models"]["bytedance/seedance-1-pro-fast"]

        self.assertTrue(wan26_fast["is_default"])
        self.assertEqual(wan26_fast["tier"], "fast")
        self.assertEqual(wan22["tier"], "legacy")
        self.assertIn("1080p", wan22["supported_resolutions"])
        self.assertIn("1080p", wan26_fast["supported_resolutions"])
        self.assertIn("1080p", hailuo["supported_resolutions"])
        self.assertIn("1080p", kling["supported_resolutions"])
        self.assertIn("1080p", seedance["supported_resolutions"])

    def test_models_endpoint_exposes_new_default(self):
        response = self.client.get("/models")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["default_model"], "wan-video/wan2.6-i2v-flash")
        self.assertTrue(
            payload["supported_models"]["wan-video/wan2.6-i2v-flash"]["is_default"]
        )


if __name__ == "__main__":
    unittest.main()
