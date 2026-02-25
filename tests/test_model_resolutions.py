import unittest
from unittest.mock import AsyncMock, patch

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
            input_params={"mode": "standard"},
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


class RoutingResolutionTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_quality_routing_respects_plan_gating(self):
        with patch(
            "model_routing.resolve_plan_tier", new_callable=AsyncMock
        ) as mock_tier:
            mock_tier.return_value = "free"
            free_result = await main.resolve_model_for_intent(
                {
                    "seconds": 9,
                    "resolution": "1080p",
                    "quality": "quality",
                    "fps": 30,
                    "has_audio": False,
                    "user_context": None,
                }
            )
            self.assertEqual(
                free_result["resolved_model_slug"], "wan-video/wan2.6-i2v-flash"
            )
            self.assertEqual(free_result["resolved"]["seconds"], 5)
            self.assertEqual(free_result["resolved"]["fps"], 30)

            mock_tier.return_value = "studio"
            studio_result = await main.resolve_model_for_intent(
                {
                    "seconds": 9,
                    "resolution": "1080p",
                    "quality": "quality",
                    "fps": 30,
                    "has_audio": False,
                    "user_context": None,
                }
            )
            self.assertEqual(studio_result["resolved_model_slug"], "kwaivgi/kling-v2.6")
            self.assertIsNone(studio_result["resolved"]["fps"])

    async def test_resolution_normalizes_to_supported_backend_values(self):
        with patch(
            "model_routing.resolve_plan_tier", new_callable=AsyncMock
        ) as mock_tier:
            mock_tier.return_value = "free"
            result = await main.resolve_model_for_intent(
                {
                    "seconds": 6,
                    "resolution": "768p",
                    "quality": "fast",
                    "fps": 24,
                    "has_audio": False,
                    "user_context": None,
                }
            )

        self.assertEqual(result["resolved_model_slug"], "wan-video/wan2.6-i2v-flash")
        self.assertEqual(result["resolved"]["resolution"], "720p")


class ModelsEndpointResolutionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._auth_enabled = main.API_AUTH_ENABLED
        main.API_AUTH_ENABLED = False
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        main.API_AUTH_ENABLED = self._auth_enabled

    def test_supported_models_expose_enriched_metadata(self):
        response = self.client.get("/models")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        wan26_fast = payload["supported_models"]["wan-video/wan2.6-i2v-flash"]

        self.assertTrue(wan26_fast["is_default"])
        self.assertEqual(wan26_fast["tier"], "fast")
        self.assertIn("supported_durations", wan26_fast)
        self.assertIn("supported_fps", wan26_fast)
        self.assertIn("blurb", wan26_fast)
        self.assertIn("tunable_params", wan26_fast)

    def test_models_endpoint_exposes_new_default(self):
        response = self.client.get("/models")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["default_model"], "wan-video/wan2.6-i2v-flash")

    def test_override_model_normalizes_resolution_for_backend(self):
        response = self.client.post(
            "/resolve_model",
            json={
                "seconds": 6,
                "resolution": "768p",
                "quality": "fast",
                "fps": 24,
                "has_audio": False,
                "model_override": "wan-video/wan2.6-i2v-flash",
                "model_params": None,
                "user_context": None,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["resolved"]["resolution"], "720p")
        self.assertEqual(payload["resolved"]["seconds"], 5)

    def test_resolve_model_endpoint_shape_and_normalization(self):
        with patch(
            "model_routing.resolve_plan_tier", new_callable=AsyncMock
        ) as mock_tier:
            mock_tier.return_value = "free"
            response = self.client.post(
                "/resolve_model",
                json={
                    "seconds": 9,
                    "resolution": "1080p",
                    "quality": "quality",
                    "fps": 60,
                    "has_audio": False,
                    "model_override": None,
                    "model_params": None,
                    "user_context": None,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("model", payload)
        self.assertIn("meta", payload)
        self.assertIn("resolved", payload)
        self.assertEqual(payload["resolved"]["seconds"], 5)
        self.assertIsNone(payload["resolved"]["fps"])


if __name__ == "__main__":
    unittest.main()
