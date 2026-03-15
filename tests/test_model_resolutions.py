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

    def test_wan25_i2v_maps_audio_fields(self):
        payload = main.build_model_payload(
            "wan-video/wan-2.5-i2v",
            image_url="https://example.com/image.jpg",
            prompt="hello",
            seconds=5,
            resolution="1080p",
            audio_url="https://example.com/audio.mp3",
        )

        self.assertEqual(payload["input"]["image"], "https://example.com/image.jpg")
        self.assertEqual(payload["input"]["prompt"], "hello")
        self.assertEqual(payload["input"]["duration"], 5)
        self.assertEqual(payload["input"]["resolution"], "1080p")
        self.assertEqual(payload["input"]["audio"], "https://example.com/audio.mp3")

    def test_hailuo02_fast_uses_first_frame_image(self):
        payload = main.build_model_payload(
            "minimax/hailuo-02-fast",
            image_url="https://example.com/image.jpg",
            prompt="hello",
            seconds=10,
            resolution="512p",
        )

        self.assertEqual(
            payload["input"]["first_frame_image"], "https://example.com/image.jpg"
        )
        self.assertEqual(payload["input"]["duration"], 10)
        self.assertEqual(payload["input"]["resolution"], "512p")

    def test_pixverse_maps_resolution_to_quality_and_tunables(self):
        payload = main.build_model_payload(
            "pixverse/pixverse-v4",
            image_url="https://example.com/image.jpg",
            prompt="hello",
            seconds=5,
            resolution="1080p",
            input_params={"motion_mode": "smooth", "sound_effect_switch": True},
        )

        self.assertEqual(payload["input"]["quality"], "1080p")
        self.assertEqual(payload["input"]["duration"], 5)
        self.assertEqual(payload["input"]["motion_mode"], "smooth")
        self.assertTrue(payload["input"]["sound_effect_switch"])

    def test_wan22_num_frames_conversion_uses_fps(self):
        payload = main.build_model_payload(
            "wan-video/wan-2.2-5b-fast",
            image_url="https://example.com/image.jpg",
            prompt="hello",
            seconds=5,
            resolution="720p",
            fps=16,
        )

        self.assertEqual(payload["input"]["frames_per_second"], 16)
        self.assertEqual(payload["input"]["num_frames"], 81)

    def test_wan22_num_frames_conversion_uses_input_params_fps_alias(self):
        payload = main.build_model_payload(
            "wan-video/wan-2.2-5b-fast",
            image_url="https://example.com/image.jpg",
            prompt="hello",
            seconds=5,
            resolution="720p",
            input_params={"fps": 24},
        )

        self.assertEqual(payload["input"]["frames_per_second"], 24)
        self.assertEqual(payload["input"]["num_frames"], 121)
        self.assertNotIn("fps", payload["input"])

    def test_wan22_num_frames_accepts_int_like_float_fps(self):
        payload = main.build_model_payload(
            "wan-video/wan-2.2-5b-fast",
            image_url="https://example.com/image.jpg",
            prompt="hello",
            seconds=5,
            resolution="720p",
            input_params={"fps": 24.0},
        )

        self.assertEqual(payload["input"]["frames_per_second"], 24)
        self.assertEqual(payload["input"]["num_frames"], 121)
        self.assertIsInstance(payload["input"]["frames_per_second"], int)


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
                free_result["resolved_model_slug"], "bytedance/seedance-1-pro-fast"
            )
            self.assertEqual(free_result["resolved"]["seconds"], 6)
            self.assertIsNone(free_result["resolved"]["fps"])
            self.assertEqual(free_result["resolved"]["resolution"], "480p")

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

        self.assertEqual(result["resolved_model_slug"], "bytedance/seedance-1-pro-fast")
        self.assertEqual(result["resolved"]["resolution"], "480p")

    async def test_pre_resolved_plan_tier_skips_secondary_profile_lookup(self):
        with patch(
            "model_routing.resolve_plan_tier", new_callable=AsyncMock
        ) as mock_tier:
            result = await main.resolve_model_for_intent(
                {
                    "seconds": 6,
                    "resolution": "768p",
                    "quality": "fast",
                    "fps": 24,
                    "plan_tier": "free",
                    "has_audio": False,
                    "user_context": {
                        "id": "00000000-0000-0000-0000-000000000000",
                        "plan_tier": "studio",
                    },
                }
            )

        self.assertEqual(result["plan_tier"], "free")
        mock_tier.assert_not_awaited()


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
        self.assertEqual(wan26_fast["slug"], "wan-video/wan2.6-i2v-flash")
        self.assertEqual(wan26_fast["tier"], "fast")
        self.assertIn("default_params", wan26_fast)
        self.assertIn("supported_durations", wan26_fast)
        self.assertIn("supported_fps", wan26_fast)
        self.assertIn("blurb", wan26_fast)
        self.assertIn("tunable_params", wan26_fast)
        self.assertIn("legacy_aliases", wan26_fast)
        self.assertIn("available_job_types", wan26_fast)
        self.assertIn("min_plan_tier", wan26_fast)

    def test_tunable_params_include_description_alias_for_help(self):
        response = self.client.get("/models")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        models_with_tunables = [
            model
            for model in payload["supported_models"].values()
            if model.get("tunable_params")
        ]

        self.assertTrue(models_with_tunables)
        for model in models_with_tunables:
            for param in model["tunable_params"]:
                if "help" in param:
                    self.assertIn("description", param)
                    self.assertEqual(param["description"], param["help"])

    def test_models_endpoint_exposes_new_default(self):
        response = self.client.get("/models")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["default_model"], "wan-video/wan2.6-i2v-flash")

    def test_models_endpoint_includes_every_supported_model(self):
        response = self.client.get("/models")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(
            set(payload["supported_models"].keys()),
            set(main.SUPPORTED_MODELS.keys()),
        )

    def test_models_endpoint_exposes_legacy_aliases_and_job_type_availability(self):
        response = self.client.get("/models")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        hailuo = payload["supported_models"]["minimax/hailuo-2.3"]
        speech_model = payload["supported_models"]["wan-video/wan-2.2-s2v"]

        self.assertEqual(hailuo["legacy_aliases"], ["minimax/hailuo-02"])
        self.assertEqual(hailuo["available_job_types"], ["prompt_only", "prompt_tts"])
        self.assertFalse(hailuo["capabilities"]["requiresAudioInput"])
        self.assertEqual(speech_model["available_job_types"], ["prompt_tts"])
        self.assertTrue(speech_model["capabilities"]["requiresAudioInput"])

    def test_override_model_rejects_when_plan_disallows_model(self):
        with patch("main.resolve_plan_tier", new_callable=AsyncMock) as mock_tier:
            mock_tier.return_value = "free"
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

        self.assertEqual(response.status_code, 403)

    def test_override_model_rejects_unknown_slug(self):
        response = self.client.post(
            "/resolve_model",
            json={
                "seconds": 6,
                "resolution": "768p",
                "quality": "fast",
                "fps": 24,
                "has_audio": False,
                "model_override": "unknown/not-a-real-model",
                "model_params": None,
                "user_context": None,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported model", response.json()["detail"])

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
        self.assertIn("resolved_model_slug", payload)
        self.assertIn("meta", payload)
        self.assertIn("resolved", payload)
        self.assertIn("plan_tier", payload)
        self.assertEqual(payload["plan_tier"], "free")
        self.assertEqual(payload["resolved"]["seconds"], 6)
        self.assertIsNone(payload["resolved"]["fps"])
        self.assertEqual(payload["resolved"]["resolution"], "480p")

    def test_resolve_model_normalizes_legacy_best_quality_alias(self):
        response = self.client.post(
            "/resolve_model",
            json={
                "seconds": 6,
                "resolution": "768p",
                "quality": "best",
                "fps": 24,
                "has_audio": False,
                "model_override": "bytedance/seedance-1-pro-fast",
                "model_params": None,
                "user_context": None,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["resolved"]["quality"], "quality")
        self.assertTrue(payload["resolved_model_slug"])

    def test_resolve_model_accepts_camel_case_payload(self):
        response = self.client.post(
            "/resolve_model",
            json={
                "seconds": 6,
                "resolution": "768p",
                "quality": "fast",
                "hasAudio": False,
                "selectedOverrideModel": "bytedance/seedance-1-pro-fast",
                "modelParams": {"fps": 24},
                "userContext": {
                    "id": "00000000-0000-0000-0000-000000000000",
                    "planTier": "creator",
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["plan_tier"], "creator")
        self.assertEqual(payload["meta"]["plan_tier"], "creator")

    def test_resolve_model_auto_route_exposes_plan_tier_and_resolved_defaults(self):
        with patch("main.resolve_plan_tier", new_callable=AsyncMock) as mock_tier:
            mock_tier.return_value = "free"
            response = self.client.post(
                "/resolve_model",
                json={
                    "seconds": 6,
                    "resolution": "1080p",
                    "quality": "fast",
                    "modelParams": {"guidance_scale": 4.5},
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["plan_tier"], "free")
        self.assertEqual(payload["meta"]["plan_tier"], "free")
        self.assertIn("resolved_defaults", payload)
        self.assertEqual(payload["resolved_defaults"]["guidance_scale"], 4.5)

        tunables = payload["meta"]["tunable_params"]
        self.assertTrue(tunables)
        self.assertIn("description", tunables[0])

    def test_resolve_model_override_returns_effective_param_defaults(self):
        with patch("main.resolve_plan_tier", new_callable=AsyncMock) as mock_tier:
            mock_tier.return_value = "creator"
            response = self.client.post(
                "/resolve_model",
                json={
                    "seconds": 10,
                    "resolution": "1080p",
                    "quality": "fast",
                    "fps": 30,
                    "model_override": "wan-video/wan2.6-i2v-flash",
                    "model_params": {"fps": 24},
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("resolved_defaults", payload)
        self.assertEqual(payload["resolved_defaults"]["fps"], 30)


class PlanTierAndFpsEnforcementTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._auth_enabled = main.API_AUTH_ENABLED
        main.API_AUTH_ENABLED = False
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        main.API_AUTH_ENABLED = self._auth_enabled

    def test_creator_can_override_to_free_model(self):
        with patch("main.resolve_plan_tier", new_callable=AsyncMock) as mock_tier:
            mock_tier.return_value = "creator"
            response = self.client.post(
                "/resolve_model",
                json={
                    "seconds": 6,
                    "resolution": "1080p",
                    "quality": "quality",
                    "fps": 24,
                    "has_audio": False,
                    "model_override": "bytedance/seedance-1-pro-fast",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["resolved"]["resolution"], "720p")

    def test_studio_can_override_to_creator_model(self):
        with patch("main.resolve_plan_tier", new_callable=AsyncMock) as mock_tier:
            mock_tier.return_value = "studio"
            response = self.client.post(
                "/resolve_model",
                json={
                    "seconds": 6,
                    "resolution": "1080p",
                    "quality": "quality",
                    "fps": 24,
                    "has_audio": False,
                    "model_override": "wan-video/wan2.6-i2v-flash",
                },
            )
        self.assertEqual(response.status_code, 200)

    def test_free_cannot_override_to_studio_model(self):
        with patch("main.resolve_plan_tier", new_callable=AsyncMock) as mock_tier:
            mock_tier.return_value = "free"
            response = self.client.post(
                "/resolve_model",
                json={
                    "seconds": 6,
                    "resolution": "1080p",
                    "quality": "quality",
                    "fps": 24,
                    "has_audio": False,
                    "model_override": "kwaivgi/kling-v2.6",
                },
            )
        self.assertEqual(response.status_code, 403)

    def test_free_cap_applies_to_routed_model(self):
        with patch(
            "model_routing.resolve_plan_tier", new_callable=AsyncMock
        ) as mock_tier:
            mock_tier.return_value = "free"
            response = self.client.post(
                "/resolve_model",
                json={
                    "seconds": 6,
                    "resolution": "1080p",
                    "quality": "fast",
                    "fps": 24,
                    "has_audio": False,
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["resolved"]["resolution"], "480p")

    def test_free_override_without_480p_support_is_blocked(self):
        with patch("main.resolve_plan_tier", new_callable=AsyncMock) as mock_tier:
            mock_tier.return_value = "free"
            response = self.client.post(
                "/resolve_model",
                json={
                    "seconds": 6,
                    "resolution": "1080p",
                    "quality": "fast",
                    "fps": 30,
                    "has_audio": False,
                    "model_override": "wan-video/wan2.6-i2v-flash",
                },
            )
        self.assertEqual(response.status_code, 403)

    def test_fps_supported_model_keeps_valid_value(self):
        with patch("main.resolve_plan_tier", new_callable=AsyncMock) as mock_tier:
            mock_tier.return_value = "creator"
            response = self.client.post(
                "/resolve_model",
                json={
                    "seconds": 6,
                    "resolution": "720p",
                    "quality": "fast",
                    "fps": 30,
                    "has_audio": False,
                    "model_override": "wan-video/wan2.6-i2v-flash",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["resolved"]["fps"], 30)

    def test_fps_unsupported_value_is_dropped(self):
        with patch("main.resolve_plan_tier", new_callable=AsyncMock) as mock_tier:
            mock_tier.return_value = "creator"
            response = self.client.post(
                "/resolve_model",
                json={
                    "seconds": 6,
                    "resolution": "720p",
                    "quality": "fast",
                    "fps": 60,
                    "has_audio": False,
                    "model_override": "wan-video/wan2.6-i2v-flash",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["resolved"]["fps"])


class ModelParamValidationTestCase(unittest.TestCase):
    def test_numeric_tunable_must_respect_declared_range(self):
        filtered = main.apply_allowed_model_params(
            "bytedance/seedance-1-pro-fast",
            {"num_inference_steps": 999, "guidance_scale": 4.5},
        )

        self.assertEqual(filtered, {"guidance_scale": 4.5})

    def test_numeric_tunable_must_respect_step(self):
        filtered = main.apply_allowed_model_params(
            "bytedance/seedance-1-pro-fast",
            {"guidance_scale": 4.25},
        )

        self.assertEqual(filtered, {})

    def test_enum_tunable_rejects_unknown_values(self):
        filtered = main.apply_allowed_model_params(
            "kwaivgi/kling-v2.6",
            {"mode": "ultra"},
        )

        self.assertEqual(filtered, {})

    def test_boolean_tunable_requires_boolean_type(self):
        filtered = main.apply_allowed_model_params(
            "minimax/hailuo-2.3",
            {"prompt_optimizer": "true"},
        )

        self.assertEqual(filtered, {})


class MuxCommandTestCase(unittest.TestCase):
    def test_mux_command_explicitly_maps_video_and_audio_streams(self):
        cmd = main._build_mux_command("ffmpeg", "in.mp4", "in.mp3", "out.mp4")

        self.assertIn("-map", cmd)
        self.assertIn("0:v:0", cmd)
        self.assertIn("1:a:0", cmd)


class QualityNormalizationTestCase(unittest.TestCase):
    def test_quality_aliases_normalize(self):
        self.assertEqual(main.normalize_quality("best"), "quality")
        self.assertEqual(main.normalize_quality("medium"), "balanced")
        self.assertEqual(main.normalize_quality("low"), "fast")

    def test_unknown_quality_defaults_to_fast(self):
        self.assertEqual(main.normalize_quality("not-a-tier"), "fast")


class ResolveModelErrorMappingTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._auth_enabled = main.API_AUTH_ENABLED
        main.API_AUTH_ENABLED = False
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        main.API_AUTH_ENABLED = self._auth_enabled

    def test_resolve_model_maps_routing_value_error_to_400(self):
        with patch(
            "main.resolve_model_for_intent",
            new_callable=AsyncMock,
        ) as mock_resolve:
            mock_resolve.side_effect = ValueError("bad intent")
            response = self.client.post(
                "/resolve_model",
                json={
                    "seconds": 6,
                    "resolution": "720p",
                    "quality": "fast",
                    "has_audio": False,
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Unable to resolve model settings", response.json()["detail"])


class ResolveJobModelErrorMappingTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_job_model_maps_routing_value_error_to_400(self):
        with patch(
            "main.resolve_model_for_intent",
            new_callable=AsyncMock,
        ) as mock_resolve:
            mock_resolve.side_effect = ValueError("no supported resolution")
            with self.assertRaises(main.HTTPException) as exc:
                await main._resolve_job_model(
                    seconds=6,
                    resolution="720p",
                    quality="fast",
                    fps=None,
                    has_audio=False,
                    user_context=None,
                    model=None,
                    model_override=None,
                    model_params=None,
                )

        self.assertEqual(exc.exception.status_code, 400)
        self.assertIn("Unable to resolve model settings", exc.exception.detail)

    async def test_resolve_job_model_rejects_unknown_override_slug(self):
        with self.assertRaises(main.HTTPException) as exc:
            await main._resolve_job_model(
                seconds=6,
                resolution="720p",
                quality="fast",
                fps=None,
                has_audio=False,
                user_context=None,
                model=None,
                model_override="unknown/not-a-real-model",
                model_params=None,
            )

        self.assertEqual(exc.exception.status_code, 400)
        self.assertIn("Unsupported model", exc.exception.detail)

    async def test_resolve_job_model_rejects_audio_required_override_for_prompt_only(self):
        with self.assertRaises(main.HTTPException) as exc:
            await main._resolve_job_model(
                seconds=6,
                resolution="1080p",
                quality="quality",
                fps=None,
                has_audio=False,
                user_context=main.UserContext(
                    id="00000000-0000-0000-0000-000000000000", plan_tier="studio"
                ),
                model=None,
                model_override="veed/fabric-1.0",
                model_params=None,
            )

        self.assertEqual(exc.exception.status_code, 400)
        self.assertIn("requires audio input", exc.exception.detail)


class JobsEndpointResponseContractTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._auth_enabled = main.API_AUTH_ENABLED
        main.API_AUTH_ENABLED = False
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        main.API_AUTH_ENABLED = self._auth_enabled

    def test_jobs_prompt_only_response_contains_video_and_final_url(self):
        with (
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
        ):
            mock_resolve.return_value = (
                "bytedance/seedance-1-pro-fast",
                {},
                {"seconds": 6, "resolution": "480p", "fps": None},
            )
            mock_generate.return_value = "https://provider/video.mp4"
            mock_fetch.return_value = b"video-bytes"
            mock_upload.return_value = "https://supabase/final.mp4"
            mock_debug.return_value = {"head_status": 200, "content_length": 100}

            response = self.client.post(
                "/jobs_prompt_only",
                json={"image_url": "https://example.com/pet.jpg", "prompt": "hello"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(set(payload.keys()), {"video_url", "final_url"})
        self.assertEqual(payload["video_url"], "https://provider/video.mp4")
        self.assertEqual(payload["final_url"], "https://supabase/final.mp4")

    def test_jobs_prompt_tts_response_contains_audio_video_and_final_url(self):
        with (
            patch("main._resolve_job_model", new_callable=AsyncMock) as mock_resolve,
            patch("main.elevenlabs_tts_bytes", new_callable=AsyncMock) as mock_tts,
            patch(
                "main.build_storage_key",
                side_effect=["audio/file.mp3", "videos/final.mp4"],
            ),
            patch("main.supabase_upload", new_callable=AsyncMock) as mock_upload,
            patch(
                "main.get_model_config",
                return_value={"capabilities": {"supportsAudioIn": True}},
            ),
            patch(
                "main.generate_video_from_prompt", new_callable=AsyncMock
            ) as mock_generate,
            patch("main.fetch_binary", new_callable=AsyncMock) as mock_fetch,
            patch(
                "main.prepare_video_for_upload_with_debug",
                return_value=(b"upload-ready", {"meets_target": True}),
            ),
            patch("main.insert_pet_video", new_callable=AsyncMock),
            patch(
                "main.collect_video_delivery_debug", new_callable=AsyncMock
            ) as mock_debug,
        ):
            mock_resolve.return_value = (
                "wan-video/wan2.6-i2v-flash",
                {},
                {"seconds": 5, "resolution": "720p", "fps": 24},
            )
            mock_tts.return_value = b"mp3"
            mock_upload.side_effect = [
                "https://supabase/audio.mp3",
                "https://supabase/final.mp4",
            ]
            mock_generate.return_value = "https://provider/video.mp4"
            mock_fetch.return_value = b"video"
            mock_debug.return_value = {"head_status": 200, "content_length": 100}

            response = self.client.post(
                "/jobs_prompt_tts",
                json={
                    "image_url": "https://example.com/pet.jpg",
                    "prompt": "hello",
                    "text": "hi",
                    "voice_id": "voice",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(set(payload.keys()), {"audio_url", "video_url", "final_url"})
        self.assertEqual(payload["audio_url"], "https://supabase/audio.mp3")
        self.assertEqual(payload["video_url"], "https://provider/video.mp4")
        self.assertEqual(payload["final_url"], "https://supabase/final.mp4")

    def test_jobs_prompt_only_accepts_frontend_camel_case_fields(self):
        with (
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
        ):
            mock_resolve.return_value = (
                "wan-video/wan2.6-i2v-flash",
                {"fps": 24},
                {"seconds": 5, "resolution": "720p", "fps": 24},
            )
            mock_generate.return_value = "https://provider/video.mp4"
            mock_fetch.return_value = b"video-bytes"
            mock_upload.return_value = "https://supabase/final.mp4"
            mock_debug.return_value = {"head_status": 200, "content_length": 100}

            response = self.client.post(
                "/jobs_prompt_only",
                json={
                    "imageUrl": "https://example.com/pet.jpg",
                    "prompt": "hello",
                    "selectedOverrideModel": "wan-video/wan2.6-i2v-flash",
                    "modelParams": {"fps": 24},
                    "userContext": {
                        "id": "00000000-0000-0000-0000-000000000000",
                        "planTier": "creator",
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        resolve_kwargs = mock_resolve.await_args.kwargs
        self.assertEqual(
            resolve_kwargs["model_override"], "wan-video/wan2.6-i2v-flash"
        )
        self.assertEqual(resolve_kwargs["model_params"], {"fps": 24})
        self.assertEqual(resolve_kwargs["user_context"].plan_tier, "creator")

    def test_jobs_prompt_tts_accepts_frontend_camel_case_fields(self):
        with (
            patch("main._resolve_job_model", new_callable=AsyncMock) as mock_resolve,
            patch("main.elevenlabs_tts_bytes", new_callable=AsyncMock) as mock_tts,
            patch(
                "main.build_storage_key",
                side_effect=["audio/file.mp3", "videos/final.mp4"],
            ),
            patch("main.supabase_upload", new_callable=AsyncMock) as mock_upload,
            patch(
                "main.get_model_config",
                return_value={"capabilities": {"supportsAudioIn": True}},
            ),
            patch(
                "main.generate_video_from_prompt", new_callable=AsyncMock
            ) as mock_generate,
            patch("main.fetch_binary", new_callable=AsyncMock) as mock_fetch,
            patch(
                "main.prepare_video_for_upload_with_debug",
                return_value=(b"upload-ready", {"meets_target": True}),
            ),
            patch("main.insert_pet_video", new_callable=AsyncMock),
            patch(
                "main.collect_video_delivery_debug", new_callable=AsyncMock
            ) as mock_debug,
        ):
            mock_resolve.return_value = (
                "wan-video/wan2.6-i2v-flash",
                {"fps": 24},
                {"seconds": 5, "resolution": "720p", "fps": 24},
            )
            mock_tts.return_value = b"mp3"
            mock_upload.side_effect = [
                "https://supabase/audio.mp3",
                "https://supabase/final.mp4",
            ]
            mock_generate.return_value = "https://provider/video.mp4"
            mock_fetch.return_value = b"video"
            mock_debug.return_value = {"head_status": 200, "content_length": 100}

            response = self.client.post(
                "/jobs_prompt_tts",
                json={
                    "imageUrl": "https://example.com/pet.jpg",
                    "prompt": "hello",
                    "text": "hi",
                    "voiceId": "voice",
                    "selectedOverrideModel": "wan-video/wan2.6-i2v-flash",
                    "modelParams": {"fps": 24},
                    "userContext": {
                        "id": "00000000-0000-0000-0000-000000000000",
                        "planTier": "creator",
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        resolve_kwargs = mock_resolve.await_args.kwargs
        self.assertEqual(
            resolve_kwargs["model_override"], "wan-video/wan2.6-i2v-flash"
        )
        self.assertEqual(resolve_kwargs["model_params"], {"fps": 24})
        self.assertEqual(resolve_kwargs["user_context"].plan_tier, "creator")

    def test_models_capability_flags_are_booleans_for_semantic_contract(self):
        response = self.client.get("/models")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        for model in payload["supported_models"].values():
            capabilities = model["capabilities"]
            self.assertIn("supportsAudioIn", capabilities)
            self.assertIn("generatesAudio", capabilities)
            self.assertIn("requiresAudioInput", capabilities)
            self.assertIsInstance(capabilities["supportsAudioIn"], bool)
            self.assertIsInstance(capabilities["generatesAudio"], bool)
            self.assertIsInstance(capabilities["requiresAudioInput"], bool)


if __name__ == "__main__":
    unittest.main()
