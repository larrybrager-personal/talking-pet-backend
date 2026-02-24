"""Central model catalog for Talking Pet backend routing and UI metadata."""

from __future__ import annotations

from copy import deepcopy

VIDEO_MODEL_ROUTES = {
    "fast": "wan-video/wan2.6-i2v-flash",
    "premium": "kwaivgi/kling-v2.6",
    "budget": "bytedance/seedance-1-pro-fast",
    "legacyFallback": "wan-video/wan-2.2-s2v",
}

SUPPORTED_MODELS = {
    "wan-video/wan2.6-i2v-flash": {
        "slug": "wan-video/wan2.6-i2v-flash",
        "name": "Wan 2.6 I2V Flash",
        "tier": "fast",
        "quality_label": "fast",
        "blurb": "Fastest turnaround for short image-to-video generations.",
        "capabilities": {
            "supportsImageToVideo": True,
            "supportsTextToVideo": False,
            "supportsAudioIn": True,
            "generatesAudio": False,
            "maxDurationSeconds": 10,
        },
        "default_params": {},
        "param_mapping": {
            "image_url": "image",
            "prompt": "prompt",
            "seconds": "duration",
            "resolution": "resolution",
            "audio_url": "audio",
            "fps": "fps",
        },
        "supported_resolutions": ["720p", "1080p"],
        "supported_durations": [6, 10],
        "supported_fps": [24, 30],
        "tunable_params": [
            {
                "key": "fps",
                "label": "FPS",
                "type": "number",
                "min": 24,
                "max": 30,
                "step": 1,
                "default": 24,
                "help": "Higher FPS can improve smoothness but may cost more.",
            }
        ],
    },
    "wan-video/wan-2.6-i2v": {
        "slug": "wan-video/wan-2.6-i2v",
        "name": "Wan 2.6 I2V",
        "tier": "premium",
        "quality_label": "balanced",
        "blurb": "Balanced quality and latency for most standard requests.",
        "capabilities": {
            "supportsImageToVideo": True,
            "supportsTextToVideo": False,
            "supportsAudioIn": True,
            "generatesAudio": False,
            "maxDurationSeconds": 10,
        },
        "default_params": {},
        "param_mapping": {
            "image_url": "image",
            "prompt": "prompt",
            "seconds": "duration",
            "resolution": "resolution",
            "audio_url": "audio",
            "fps": "fps",
        },
        "supported_resolutions": ["720p", "1080p"],
        "supported_durations": [6, 10],
        "supported_fps": [24, 30],
        "tunable_params": [
            {
                "key": "fps",
                "label": "FPS",
                "type": "number",
                "min": 24,
                "max": 30,
                "step": 1,
                "default": 24,
                "help": "Higher FPS can improve smoothness but may cost more.",
            }
        ],
    },
    "minimax/hailuo-2.3": {
        "slug": "minimax/hailuo-2.3",
        "name": "Hailuo 2.3",
        "tier": "premium",
        "quality_label": "quality",
        "blurb": "High-fidelity motion output with slower runtime than flash models.",
        "capabilities": {
            "supportsImageToVideo": True,
            "supportsTextToVideo": False,
            "supportsAudioIn": False,
            "generatesAudio": False,
            "maxDurationSeconds": 10,
        },
        "default_params": {"prompt_optimizer": False},
        "param_mapping": {
            "image_url": "first_frame_image",
            "prompt": "prompt",
            "seconds": "duration",
            "resolution": "resolution",
        },
        "supported_resolutions": ["512p", "768p", "1080p"],
        "supported_durations": [6, 10],
        "supported_fps": [],
        "tunable_params": [
            {
                "key": "prompt_optimizer",
                "label": "Prompt optimizer",
                "type": "boolean",
                "default": False,
                "help": "May improve prompt adherence.",
            }
        ],
    },
    "minimax/hailuo-2.3-fast": {
        "slug": "minimax/hailuo-2.3-fast",
        "name": "Hailuo 2.3 Fast",
        "tier": "budget",
        "quality_label": "cheap",
        "blurb": "Lower-cost Hailuo profile for quick iteration.",
        "capabilities": {
            "supportsImageToVideo": True,
            "supportsTextToVideo": False,
            "supportsAudioIn": False,
            "generatesAudio": False,
            "maxDurationSeconds": 10,
        },
        "default_params": {"prompt_optimizer": False},
        "param_mapping": {
            "image_url": "first_frame_image",
            "prompt": "prompt",
            "seconds": "duration",
            "resolution": "resolution",
        },
        "supported_resolutions": ["512p", "768p", "1080p"],
        "supported_durations": [6, 10],
        "supported_fps": [],
        "tunable_params": [
            {
                "key": "prompt_optimizer",
                "label": "Prompt optimizer",
                "type": "boolean",
                "default": False,
                "help": "May improve prompt adherence.",
            }
        ],
    },
    "kwaivgi/kling-v2.6": {
        "slug": "kwaivgi/kling-v2.6",
        "name": "Kling v2.6",
        "tier": "premium",
        "quality_label": "quality",
        "blurb": "Best premium visual fidelity for paid tiers.",
        "capabilities": {
            "supportsImageToVideo": True,
            "supportsTextToVideo": False,
            "supportsAudioIn": False,
            "generatesAudio": True,
            "maxDurationSeconds": 10,
        },
        "default_params": {"mode": "standard", "aspect_ratio": "1:1"},
        "param_mapping": {
            "image_url": "start_image",
            "prompt": "prompt",
            "seconds": "duration",
            "resolution": "aspect_ratio",
        },
        "supported_resolutions": ["720p", "1080p"],
        "supported_durations": [5, 10],
        "supported_fps": [],
        "tunable_params": [
            {
                "key": "mode",
                "label": "Mode",
                "type": "enum",
                "options": [
                    {"value": "standard", "label": "Standard"},
                    {"value": "pro", "label": "Pro"},
                ],
                "default": "standard",
                "help": "Pro mode can improve quality with longer runtime.",
            }
        ],
    },
    "kwaivgi/kling-v2.5-turbo-pro": {
        "slug": "kwaivgi/kling-v2.5-turbo-pro",
        "name": "Kling v2.5 Turbo Pro",
        "tier": "fast",
        "quality_label": "balanced",
        "blurb": "Faster Kling profile when you want quality without full premium cost.",
        "capabilities": {
            "supportsImageToVideo": True,
            "supportsTextToVideo": False,
            "supportsAudioIn": False,
            "generatesAudio": True,
            "maxDurationSeconds": 10,
        },
        "default_params": {"mode": "standard", "aspect_ratio": "1:1"},
        "param_mapping": {
            "image_url": "start_image",
            "prompt": "prompt",
            "seconds": "duration",
            "resolution": "aspect_ratio",
        },
        "supported_resolutions": ["720p", "1080p"],
        "supported_durations": [5, 10],
        "supported_fps": [],
        "tunable_params": [
            {
                "key": "mode",
                "label": "Mode",
                "type": "enum",
                "options": [
                    {"value": "standard", "label": "Standard"},
                    {"value": "pro", "label": "Pro"},
                ],
                "default": "standard",
                "help": "Pro mode can improve quality with longer runtime.",
            }
        ],
    },
    "wan-video/wan-2.2-s2v": {
        "slug": "wan-video/wan-2.2-s2v",
        "name": "Wan v2.2 S2V",
        "tier": "legacy",
        "quality_label": "balanced",
        "blurb": "Legacy speech-to-video path with native audio sync.",
        "capabilities": {
            "supportsImageToVideo": True,
            "supportsTextToVideo": False,
            "supportsAudioIn": True,
            "generatesAudio": True,
            "maxDurationSeconds": 10,
        },
        "default_params": {"guidance_scale": 7.5, "num_inference_steps": 25},
        "param_mapping": {
            "image_url": "image",
            "prompt": "prompt",
            "seconds": "duration",
            "resolution": "resolution",
            "audio_url": "audio",
        },
        "supported_resolutions": ["768p", "1080p"],
        "supported_durations": [6, 10],
        "supported_fps": [],
        "tunable_params": [
            {
                "key": "guidance_scale",
                "label": "Guidance",
                "type": "number",
                "min": 1,
                "max": 15,
                "step": 0.5,
                "default": 7.5,
                "help": "Higher values follow prompt text more strongly.",
            },
            {
                "key": "num_inference_steps",
                "label": "Steps",
                "type": "number",
                "min": 10,
                "max": 50,
                "step": 1,
                "default": 25,
                "help": "More steps can improve quality with added runtime.",
            },
        ],
    },
    "bytedance/seedance-1-pro-fast": {
        "slug": "bytedance/seedance-1-pro-fast",
        "name": "SeeDance-1 Pro Fast",
        "tier": "budget",
        "quality_label": "cheap",
        "blurb": "Cost-efficient generations for budget-sensitive workloads.",
        "capabilities": {
            "supportsImageToVideo": True,
            "supportsTextToVideo": False,
            "supportsAudioIn": False,
            "generatesAudio": False,
            "maxDurationSeconds": 10,
        },
        "default_params": {"guidance_scale": 7.5, "num_inference_steps": 20},
        "param_mapping": {
            "image_url": "image",
            "prompt": "prompt",
            "seconds": "duration",
            "resolution": "resolution",
        },
        "supported_resolutions": ["480p", "720p", "1080p"],
        "supported_durations": [6, 10],
        "supported_fps": [],
        "tunable_params": [
            {
                "key": "guidance_scale",
                "label": "Guidance",
                "type": "number",
                "min": 1,
                "max": 15,
                "step": 0.5,
                "default": 7.5,
                "help": "Higher values follow prompt text more strongly.",
            },
            {
                "key": "num_inference_steps",
                "label": "Steps",
                "type": "number",
                "min": 10,
                "max": 50,
                "step": 1,
                "default": 20,
                "help": "More steps can improve quality with added runtime.",
            },
        ],
    },
    "bytedance/seedance-1-pro": {
        "slug": "bytedance/seedance-1-pro",
        "name": "SeeDance-1 Pro",
        "tier": "premium",
        "quality_label": "quality",
        "blurb": "Higher-quality SeeDance profile at increased cost.",
        "capabilities": {
            "supportsImageToVideo": True,
            "supportsTextToVideo": False,
            "supportsAudioIn": False,
            "generatesAudio": False,
            "maxDurationSeconds": 10,
        },
        "default_params": {"guidance_scale": 7.5, "num_inference_steps": 25},
        "param_mapping": {
            "image_url": "image",
            "prompt": "prompt",
            "seconds": "duration",
            "resolution": "resolution",
        },
        "supported_resolutions": ["480p", "720p", "1080p"],
        "supported_durations": [6, 10],
        "supported_fps": [],
        "tunable_params": [
            {
                "key": "guidance_scale",
                "label": "Guidance",
                "type": "number",
                "min": 1,
                "max": 15,
                "step": 0.5,
                "default": 7.5,
                "help": "Higher values follow prompt text more strongly.",
            },
            {
                "key": "num_inference_steps",
                "label": "Steps",
                "type": "number",
                "min": 10,
                "max": 50,
                "step": 1,
                "default": 25,
                "help": "More steps can improve quality with added runtime.",
            },
        ],
    },
}

DEFAULT_MODEL = VIDEO_MODEL_ROUTES["fast"]
PROMPT_ONLY_FALLBACK_MODEL = DEFAULT_MODEL


def get_supported_models() -> dict:
    """Return a deep copy so callers can safely enrich metadata per request."""

    return deepcopy(SUPPORTED_MODELS)
