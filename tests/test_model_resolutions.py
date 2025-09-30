import unittest

from fastapi.testclient import TestClient

import main


class BuildModelPayloadResolutionTestCase(unittest.TestCase):
    def test_hailuo_passes_1080p_resolution(self):
        payload = main.build_model_payload(
            "minimax/hailuo-02",
            image_url="https://example.com/image.jpg",
            prompt="hello",
            seconds=6,
            resolution="1080p",
        )

        self.assertEqual(payload["input"]["resolution"], "1080p")

    def test_seedance_passes_1080p_resolution(self):
        payload = main.build_model_payload(
            "bytedance/seedance-1-lite",
            image_url="https://example.com/image.jpg",
            prompt="hello",
            seconds=6,
            resolution="1080p",
        )

        self.assertEqual(payload["input"]["resolution"], "1080p")

    def test_kling_switches_to_pro_mode_for_1080p(self):
        payload = main.build_model_payload(
            "kwaivgi/kling-v2.1",
            image_url="https://example.com/image.jpg",
            prompt="hello",
            seconds=6,
            resolution="1080p",
        )

        self.assertEqual(payload["input"]["mode"], "pro")
        self.assertEqual(payload["input"]["aspect_ratio"], "16:9")

    def test_kling_uses_standard_mode_for_non_1080p(self):
        payload = main.build_model_payload(
            "kwaivgi/kling-v2.1",
            image_url="https://example.com/image.jpg",
            prompt="hello",
            seconds=6,
            resolution="768p",
        )

        self.assertEqual(payload["input"]["mode"], "standard")
        self.assertEqual(payload["input"]["aspect_ratio"], "1:1")


class ModelsEndpointResolutionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._auth_enabled = main.API_AUTH_ENABLED
        main.API_AUTH_ENABLED = False
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        main.API_AUTH_ENABLED = self._auth_enabled

    def test_supported_models_expose_resolutions(self):
        response = self.client.get("/models")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        hailuo = payload["supported_models"]["minimax/hailuo-02"]
        kling = payload["supported_models"]["kwaivgi/kling-v2.1"]
        seedance = payload["supported_models"]["bytedance/seedance-1-lite"]

        self.assertIn("1080p", hailuo["supported_resolutions"])
        self.assertIn("1080p", kling["supported_resolutions"])
        self.assertIn("1080p", seedance["supported_resolutions"])


if __name__ == "__main__":
    unittest.main()
