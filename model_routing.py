"""Routing helpers for model normalization and intent-based model resolution."""

from __future__ import annotations

import os
from typing import Any

import httpx

from model_registry import DEFAULT_MODEL, SUPPORTED_MODELS, VIDEO_MODEL_ROUTES

LEGACY_MODEL_ALIASES = {
    "minimax/hailuo-02": "minimax/hailuo-2.3",
    "kwaivgi/kling-v2.1": "kwaivgi/kling-v2.6",
    "bytedance/seedance-1-lite": "bytedance/seedance-1-pro-fast",
    "wan-video/wan-2.1": "wan-video/wan2.6-i2v-flash",
}

PLAN_RANK = {"free": 0, "creator": 1, "studio": 2, "ultimate": 3}
RESOLUTION_ORDER = ["480p", "512p", "720p", "768p", "1080p"]
PLAN_MAX_RESOLUTION = {
    "free": "480p",
    "creator": "768p",
    "studio": "1080p",
    "ultimate": "1080p",
}


class IntentResolutionResult(dict):
    """Small typed dict-like container for the resolved routing payload."""


def normalize_quality(
    quality: str | None,
) -> str:
    """Normalize legacy quality aliases to supported routing quality tiers."""

    normalized = str(quality or "fast").strip().lower()
    quality_aliases = {
        "best": "quality",
        "high": "quality",
        "medium": "balanced",
        "low": "fast",
    }
    normalized = quality_aliases.get(normalized, normalized)
    if normalized not in {"fast", "balanced", "cheap", "quality"}:
        return "fast"
    return normalized


def normalize_video_model(model: str | None) -> str:
    """Normalize legacy or unknown model ids to a supported model slug."""

    if not model:
        return DEFAULT_MODEL
    normalized = LEGACY_MODEL_ALIASES.get(model, model)
    if normalized in SUPPORTED_MODELS:
        return normalized
    return DEFAULT_MODEL


def get_default_video_model(mode: str = "fast") -> str:
    """Return default model slug for a routing mode, falling back to fast."""

    return VIDEO_MODEL_ROUTES.get(mode, VIDEO_MODEL_ROUTES["fast"])


async def resolve_plan_tier(
    user_context: dict[str, Any] | None, supabase_url: str, supabase_service_role: str
) -> str:
    """Resolve the effective plan tier using trusted profile lookup when available."""

    fallback = (user_context or {}).get("plan_tier") or "free"
    fallback = str(fallback).strip().lower()
    if fallback not in PLAN_RANK:
        fallback = "free"

    user_id = (user_context or {}).get("id")
    if not user_id or not supabase_url or not supabase_service_role:
        return fallback

    url = f"{supabase_url}/rest/v1/profiles"
    headers = {
        "Authorization": f"Bearer {supabase_service_role}",
        "apikey": supabase_service_role,
    }
    params = {"id": f"eq.{user_id}", "select": "tier", "limit": "1"}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers=headers, params=params)
        if response.status_code >= 400:
            return fallback
        rows = response.json()
        if rows and isinstance(rows, list):
            db_tier = str(rows[0].get("tier") or "free").strip().lower()
            if db_tier in PLAN_RANK:
                return db_tier
    except (httpx.HTTPError, ValueError, TypeError):
        return fallback
    return fallback


def _is_plan_at_least(plan_tier: str, required_tier: str) -> bool:
    return PLAN_RANK.get(plan_tier, 0) >= PLAN_RANK.get(required_tier, 0)


def get_model_min_plan_tier(model_slug: str) -> str:
    model = SUPPORTED_MODELS.get(model_slug, {})
    min_plan_tier = str(model.get("min_plan_tier") or "free").strip().lower()
    if min_plan_tier not in PLAN_RANK:
        return "free"
    return min_plan_tier


def is_model_allowed_for_plan(model_slug: str, plan_tier: str) -> bool:
    return _is_plan_at_least(plan_tier, get_model_min_plan_tier(model_slug))


def _resolution_rank(resolution: str) -> int:
    try:
        return RESOLUTION_ORDER.index(resolution)
    except ValueError:
        return -1


def cap_resolution_for_plan(plan_tier: str, requested_resolution: str) -> str:
    plan_cap = PLAN_MAX_RESOLUTION.get(plan_tier, PLAN_MAX_RESOLUTION["free"])
    requested_rank = _resolution_rank(requested_resolution)
    cap_rank = _resolution_rank(plan_cap)
    if requested_rank == -1:
        return plan_cap
    if requested_rank <= cap_rank:
        return requested_resolution
    return plan_cap


def _snap_seconds(requested_seconds: int, supported_durations: list[int]) -> int:
    if not supported_durations:
        return requested_seconds
    sorted_durations = sorted(set(supported_durations))
    candidates = [value for value in sorted_durations if value <= requested_seconds]
    if candidates:
        return max(candidates)
    return min(sorted_durations, key=lambda value: abs(value - requested_seconds))


def _normalize_resolution(
    model_slug: str, resolution: str, plan_tier: str
) -> str | None:
    supported = SUPPORTED_MODELS[model_slug].get("supported_resolutions", [])
    if not supported:
        return resolution

    capped_resolution = cap_resolution_for_plan(plan_tier, resolution)
    plan_cap = PLAN_MAX_RESOLUTION.get(plan_tier, PLAN_MAX_RESOLUTION["free"])
    cap_rank = _resolution_rank(plan_cap)

    if capped_resolution in supported:
        return capped_resolution

    supported_not_above_cap = [
        value
        for value in supported
        if _resolution_rank(value) != -1 and _resolution_rank(value) <= cap_rank
    ]
    if not supported_not_above_cap:
        return None

    capped_rank = _resolution_rank(capped_resolution)
    if capped_rank == -1:
        return max(supported_not_above_cap, key=_resolution_rank)

    lower_or_equal = [
        value
        for value in supported_not_above_cap
        if _resolution_rank(value) <= capped_rank
    ]
    if lower_or_equal:
        return max(lower_or_equal, key=_resolution_rank)
    return min(supported_not_above_cap, key=_resolution_rank)


def _normalize_fps(requested_fps: int | None, supported_fps: list[int]) -> int | None:
    if requested_fps is None or not supported_fps:
        return None
    if requested_fps in supported_fps:
        return requested_fps
    return None


def _meta_for_slug(model_slug: str) -> dict[str, Any]:
    config = SUPPORTED_MODELS[model_slug]
    return {
        "name": config["name"],
        "tier": config["tier"],
        "quality_label": config["quality_label"],
        "blurb": config["blurb"],
        "supported_durations": config["supported_durations"],
        "supported_fps": config["supported_fps"],
        "supported_resolutions": config["supported_resolutions"],
        "tunable_params": config["tunable_params"],
        "min_plan_tier": get_model_min_plan_tier(model_slug),
    }


def _pick_model_for_quality(quality: str, plan_tier: str) -> str:
    if plan_tier == "free":
        return "bytedance/seedance-1-pro-fast"

    if quality == "quality":
        if _is_plan_at_least(plan_tier, "studio"):
            return "kwaivgi/kling-v2.6"
        if _is_plan_at_least(plan_tier, "creator"):
            return "wan-video/wan-2.6-i2v"
        return "wan-video/wan2.6-i2v-flash"
    if quality == "cheap":
        if _is_plan_at_least(plan_tier, "creator"):
            return "bytedance/seedance-1-pro-fast"
        return "wan-video/wan2.6-i2v-flash"
    if quality == "balanced":
        if _is_plan_at_least(plan_tier, "creator"):
            return "wan-video/wan-2.6-i2v"
        return "wan-video/wan2.6-i2v-flash"
    return "wan-video/wan2.6-i2v-flash"


async def resolve_model_for_intent(intent: dict[str, Any]) -> IntentResolutionResult:
    """Resolve a model based on user intent and plan tier.

    Legacy speech-to-video model wan-video/wan-2.2-s2v is manual-override only.
    """

    requested_quality = normalize_quality(intent.get("quality"))

    seconds = int(intent.get("seconds") or 6)
    resolution = str(intent.get("resolution") or "768p")
    fps = intent.get("fps")

    user_context = intent.get("user_context") or {}
    plan_tier = await resolve_plan_tier(
        user_context,
        os.getenv("SUPABASE_URL", ""),
        os.getenv("SUPABASE_SERVICE_ROLE", ""),
    )

    model_slug = _pick_model_for_quality(requested_quality, plan_tier)
    model_config = SUPPORTED_MODELS[model_slug]

    resolved_seconds = _snap_seconds(
        seconds, model_config.get("supported_durations", [])
    )
    resolved_resolution = _normalize_resolution(model_slug, resolution, plan_tier)
    if resolved_resolution is None:
        raise ValueError(
            f"No supported resolution for model {model_slug} within {plan_tier} plan limits"
        )
    resolved_fps = _normalize_fps(fps, model_config.get("supported_fps", []))

    resolved_defaults = model_config.get("default_params", {}).copy()
    if resolved_fps is not None and "fps" in model_config.get("param_mapping", {}):
        resolved_defaults["fps"] = resolved_fps

    return IntentResolutionResult(
        {
            "resolved_model_slug": model_slug,
            "resolved_defaults": resolved_defaults,
            "resolved_meta": _meta_for_slug(model_slug),
            "resolved": {
                "seconds": resolved_seconds,
                "fps": resolved_fps,
                "resolution": resolved_resolution,
                "quality": requested_quality,
            },
            "plan_tier": plan_tier,
        }
    )


def apply_allowed_model_params(
    model_slug: str, model_params: dict[str, Any] | None
) -> dict[str, Any]:
    """Filter and validate client model params against model tunable specs."""

    if not model_params:
        return {}

    config = SUPPORTED_MODELS[model_slug]
    tunables = {item["key"]: item for item in config.get("tunable_params", [])}

    normalized: dict[str, Any] = {}
    for key, value in model_params.items():
        spec = tunables.get(key)
        if not spec:
            continue

        spec_type = spec.get("type")
        if spec_type == "boolean":
            if isinstance(value, bool):
                normalized[key] = value
            continue

        if spec_type == "enum":
            options = {item.get("value") for item in spec.get("options", [])}
            if value in options:
                normalized[key] = value
            continue

        if spec_type == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue

            min_value = spec.get("min")
            max_value = spec.get("max")
            step = spec.get("step")
            if min_value is not None and value < min_value:
                continue
            if max_value is not None and value > max_value:
                continue
            if step:
                base = min_value if min_value is not None else 0
                remainder = (float(value) - float(base)) / float(step)
                if abs(remainder - round(remainder)) > 1e-9:
                    continue

            normalized[key] = int(value) if isinstance(value, int) else float(value)

    return normalized
