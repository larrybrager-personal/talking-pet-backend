"""
Minimal FastAPI backend (cleaned) for Talking Pet MVP.
- ElevenLabs TTS + Replicate tiered model routing + Supabase uploads
- Keeps one debug helper: /debug/head to inspect public file headers
"""

import asyncio
import ipaddress
import json
import logging
import os
import secrets
import importlib
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
from http import HTTPStatus
from functools import lru_cache
from datetime import datetime, timezone
from typing import Any, Tuple
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

try:  # Pydantic v2
    from pydantic import ConfigDict
except ImportError:  # Pydantic v1
    ConfigDict = None

from model_registry import (
    DEFAULT_MODEL,
    SUPPORTED_MODELS,
    VIDEO_MODEL_ROUTES,
)
from model_routing import (
    PLAN_MAX_RESOLUTION,
    apply_allowed_model_params,
    cap_resolution_for_plan,
    get_default_video_model,
    get_model_min_plan_tier,
    is_model_allowed_for_plan,
    normalize_video_model,
    resolve_model_for_intent,
    normalize_quality,
    resolve_explicit_video_model,
    resolve_plan_tier,
)

# ===== Environment =====
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY", "")
ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "*")

# e.g. https://<project>.supabase.co
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE = os.getenv("SUPABASE_SERVICE_ROLE", "")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "pets")

# Replicate configuration
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN", "")

# API authentication toggle
API_AUTH_ENABLED = os.getenv("API_AUTH_ENABLED", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "")

# TTS tuning
TTS_OUTPUT_FORMAT = os.getenv("TTS_OUTPUT_FORMAT", "mp3_44100_64")
TTS_MAX_CHARS = int(os.getenv("TTS_MAX_CHARS", "600"))
VIDEO_UPLOAD_TARGET_BYTES = int(os.getenv("VIDEO_UPLOAD_TARGET_BYTES", "9500000"))
IDEMPOTENCY_POLL_INTERVAL_SEC = float(os.getenv("IDEMPOTENCY_POLL_INTERVAL_SEC", "1"))
IDEMPOTENCY_MAX_WAIT_SEC = float(os.getenv("IDEMPOTENCY_MAX_WAIT_SEC", "900"))
ENABLE_FINAL_VIDEO_DEBUG = os.getenv("ENABLE_FINAL_VIDEO_DEBUG", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
REPLICATE_POLL_INTERVAL_SEC = float(os.getenv("REPLICATE_POLL_INTERVAL_SEC", "2"))
REPLICATE_POLL_TIMEOUT_SEC = float(os.getenv("REPLICATE_POLL_TIMEOUT_SEC", "900"))
FETCH_MAX_BYTES = int(os.getenv("FETCH_MAX_BYTES", "52428800"))
DEBUG_FETCH_MAX_BYTES = int(os.getenv("DEBUG_FETCH_MAX_BYTES", "15728640"))
MAX_REDIRECT_HOPS = int(os.getenv("MAX_REDIRECT_HOPS", "5"))
ALLOW_PRIVATE_URL_FETCHES = os.getenv("ALLOW_PRIVATE_URL_FETCHES", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

PUBLIC_BASE = f"{SUPABASE_URL}/storage/v1/object/public"
UPLOAD_BASE = f"{SUPABASE_URL}/storage/v1/object"

# ===== App =====
app = FastAPI(title="Talking Pet Backend (Multi-Model)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN] if ALLOWED_ORIGIN != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger("talking_pet_backend")

# Backward-compatible re-exports used by tests/importers.
_ROUTING_HELPERS_COMPAT = (normalize_video_model, get_default_video_model)


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    """Return a stable error envelope while preserving FastAPI-compatible detail."""

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail if isinstance(exc.detail, str) else "Request failed.",
            "detail": exc.detail,
            "status": exc.status_code,
        },
    )


@app.exception_handler(StarletteHTTPException)
async def starlette_http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Apply the same envelope for Starlette-raised HTTP errors (e.g. 404/405)."""

    return await http_exception_handler(
        request, HTTPException(exc.status_code, exc.detail)
    )


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    """Surface a friendly summary and preserve full validation detail payload."""

    errors = exc.errors()
    summary = "Validation error."
    if errors:
        first = errors[0]
        message = first.get("msg", "Validation error.")
        location = ".".join(
            str(part) for part in first.get("loc", []) if part != "body"
        )
        summary = f"{location}: {message}" if location else str(message)

    return JSONResponse(
        status_code=422,
        content={
            "error": summary,
            "detail": errors,
            "status": 422,
        },
    )


def _log_unexpected_job_error(
    *,
    endpoint: str,
    exc: Exception,
    model: str | None = None,
    request_id: str | None = None,
    user_id: str | None = None,
) -> None:
    """Emit structured, non-PII diagnostics for unexpected request failures."""

    logger.exception(
        "unexpected_error endpoint=%s request_id=%s user_id=%s model=%s error_type=%s",
        endpoint,
        request_id,
        user_id,
        model,
        type(exc).__name__,
    )


def _is_non_public_ip(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True when an IP should not be fetched from user-controlled inputs."""

    return (
        not ip_obj.is_global
        or ip_obj.is_loopback
        or ip_obj.is_private
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
    )


def _validate_outbound_url(url: str, *, allow_private: bool = False) -> None:
    """Validate outbound URL scheme/host and block private-network SSRF targets."""

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(400, "URL must use http or https.")

    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(400, "URL must include a valid hostname.")

    if allow_private:
        return

    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        if _is_non_public_ip(literal_ip):
            raise HTTPException(400, "URL host is not publicly routable.")
        return

    try:
        default_port = 443 if parsed.scheme == "https" else 80
        addr_info = socket.getaddrinfo(
            hostname,
            parsed.port or default_port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise HTTPException(400, "URL hostname could not be resolved.") from exc

    for entry in addr_info:
        sockaddr = entry[4]
        if not sockaddr:
            continue
        resolved_host = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(resolved_host)
        except ValueError:
            continue
        if _is_non_public_ip(ip_obj):
            raise HTTPException(400, "URL host resolves to a non-public address.")


class RequestModel(BaseModel):
    """Pydantic v1/v2-compatible request base model config."""

    if ConfigDict is not None:
        model_config = ConfigDict(populate_by_name=True, extra="ignore")
    else:

        class Config:
            allow_population_by_field_name = True
            extra = "ignore"


# ===== Auth =====
async def require_auth(request: Request) -> None:
    """Enforce bearer token authentication when enabled via configuration."""

    if not API_AUTH_ENABLED:
        return

    if not API_AUTH_TOKEN:
        raise HTTPException(
            500,
            "API authentication is enabled but API_AUTH_TOKEN is not configured.",
        )

    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(401, "Missing Authorization header")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Authorization header must be 'Bearer <token>'")

    if not secrets.compare_digest(token, API_AUTH_TOKEN):
        raise HTTPException(403, "Invalid API token")


# ===== Models =====
class UserContext(RequestModel):
    """Authenticated user metadata forwarded by the studio frontend."""

    id: str
    email: str | None = None
    name: str | None = None
    plan_tier: str | None = Field(default=None, alias="planTier")


class ModelIntentRequest(RequestModel):
    """High-level model routing intent used by automatic backend selection."""

    seconds: int = 6
    resolution: str = "768p"
    quality: str = "fast"
    fps: int | None = None
    has_audio: bool = Field(default=False, alias="hasAudio")
    model_override: str | None = Field(default=None, alias="selectedOverrideModel")
    model_params: dict[str, Any] | None = Field(default=None, alias="modelParams")
    user_context: UserContext | None = Field(default=None, alias="userContext")


class JobPromptOnly(BaseModel):
    """Request body for generating a video directly from a prompt.

    Attributes:
        image_url: Publicly accessible image that provides the first frame.
        prompt: Text prompt describing the desired animation.
        seconds: Duration of the generated video.
        resolution: Target output resolution, defaults to 768p.
        model: Optional Replicate model identifier. Defaults to the fast routing model.
    """

    image_url: str
    prompt: str
    seconds: int = 6
    resolution: str = "768p"
    quality: str = "fast"
    fps: int | None = None
    model: str | None = None
    model_override: str | None = None
    model_params: dict[str, Any] | None = None
    user_context: UserContext | None = None
    request_id: str | None = None


class JobPromptTTS(BaseModel):
    """Request body for generating a video and matching audio.

    Extends :class:`JobPromptOnly` with script text and desired ElevenLabs
    voice identifier so the backend can synthesize speech and mux it with the
    generated video.

    Attributes:
        image_url: Publicly accessible image that provides the first frame.
        prompt: Text prompt describing the desired animation.
        text: Script text to synthesize with TTS.
        voice_id: ElevenLabs voice identifier.
        seconds: Duration of the generated video.
        resolution: Target output resolution, defaults to 768p.
        model: Optional Replicate model identifier. Defaults to the fast routing model.
    """

    image_url: str
    prompt: str
    text: str
    voice_id: str
    seconds: int = 6
    resolution: str = "768p"
    quality: str = "fast"
    fps: int | None = None
    model: str | None = None
    model_override: str | None = None
    model_params: dict[str, Any] | None = None
    user_context: UserContext | None = None
    request_id: str | None = None


class HeadRequest(BaseModel):
    """Request body for the ``/debug/head`` endpoint."""

    url: str


class FinalVideoDebugRequest(BaseModel):
    """Request body for the ``/debug/final_video`` endpoint."""

    url: str
    include_compression_debug: bool = False
    target_bytes: int | None = None


def to_model_dict(model: BaseModel) -> dict[str, Any]:
    """Compat helper for pydantic v1/v2 model serialization."""

    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


# ===== Helpers =====


def _resolve_generation_settings(
    *,
    model_slug: str,
    config: dict[str, Any],
    seconds: int,
    resolution: str,
    fps: int | None,
    quality: str,
    plan_tier: str,
) -> dict[str, Any]:
    """Normalize generation settings to values supported by the selected model."""

    supported_durations = config.get("supported_durations", [])
    if supported_durations:
        lower_or_equal = [value for value in supported_durations if value <= seconds]
        resolved_seconds = (
            max(lower_or_equal) if lower_or_equal else min(supported_durations)
        )
    else:
        resolved_seconds = seconds

    requested_resolution = cap_resolution_for_plan(plan_tier, resolution)
    supported_resolutions = config.get("supported_resolutions", [])
    if requested_resolution in supported_resolutions:
        resolved_resolution = requested_resolution
    else:
        resolution_order = ["480p", "512p", "720p", "768p", "1080p"]

        def rank(value: str) -> int:
            try:
                return resolution_order.index(value)
            except ValueError:
                return -1

        cap = PLAN_MAX_RESOLUTION.get(plan_tier, PLAN_MAX_RESOLUTION["free"])
        cap_rank = rank(cap)
        req_rank = rank(requested_resolution)
        within_cap = [
            value
            for value in supported_resolutions
            if rank(value) != -1 and rank(value) <= cap_rank
        ]
        if not within_cap:
            raise HTTPException(
                403,
                "Requested model/resolution requires a higher plan. Please upgrade your plan tier.",
            )

        lower_or_equal = [value for value in within_cap if rank(value) <= req_rank]
        resolved_resolution = (
            max(lower_or_equal, key=rank)
            if lower_or_equal
            else min(within_cap, key=rank)
        )

    supported_fps = config.get("supported_fps", [])
    supports_fps = bool(supported_fps) and "fps" in config.get("param_mapping", {})
    resolved_fps = fps if (supports_fps and fps in supported_fps) else None

    return {
        "seconds": resolved_seconds,
        "fps": resolved_fps,
        "resolution": resolved_resolution,
        "quality": quality,
    }


def get_model_config(model: str) -> dict:
    """Get configuration for a supported model.

    Args:
        model: Model identifier (e.g., 'wan-video/wan2.6-i2v-flash')

    Returns:
        Model configuration dictionary

    Raises:
        HTTPException: If model is not supported
    """
    if model not in SUPPORTED_MODELS:
        supported_list = ", ".join(SUPPORTED_MODELS.keys())
        raise HTTPException(
            400,
            f"Unsupported model '{model}'. Supported models: {supported_list}",
        )
    config = SUPPORTED_MODELS[model]
    if config.get("runnable", True) is False:
        raise HTTPException(
            400,
            f"Model '{model}' is experimental and not yet runnable.",
        )
    return config


def build_model_payload(
    model: str,
    image_url: str,
    prompt: str,
    seconds: int,
    resolution: str,
    audio_url: str = None,
    fps: int | None = None,
    input_params: dict[str, Any] | None = None,
) -> dict:
    """Build the payload for a specific model based on its parameter mapping."""

    config = get_model_config(model)
    param_mapping = config["param_mapping"]

    payload = {"input": (input_params or {}).copy()}

    if "fps" in param_mapping:
        mapped_fps_key = param_mapping["fps"]
        raw_fps = payload["input"].get("fps")
        if raw_fps is not None and mapped_fps_key != "fps":
            payload["input"].pop("fps", None)
            payload["input"][mapped_fps_key] = raw_fps

    if "image_url" in param_mapping:
        payload["input"][param_mapping["image_url"]] = image_url
    if "prompt" in param_mapping:
        payload["input"][param_mapping["prompt"]] = prompt

    effective_fps: int | None = None
    if "fps" in param_mapping:
        mapped_fps_key = param_mapping["fps"]
        if fps is not None:
            effective_fps = fps
        elif isinstance(payload["input"].get(mapped_fps_key), int):
            effective_fps = payload["input"].get(mapped_fps_key)
        elif isinstance(config.get("default_params", {}).get(mapped_fps_key), int):
            effective_fps = config["default_params"].get(mapped_fps_key)

    if "seconds" in param_mapping:
        duration_key = param_mapping["seconds"]
        if duration_key == "num_frames":
            resolved_fps = effective_fps or 16
            frame_count = (seconds * resolved_fps) + 1
            frame_range = config.get("frame_count_range", {})
            min_frames = int(frame_range.get("min", 81))
            max_frames = int(frame_range.get("max", 121))
            payload["input"][duration_key] = max(
                min_frames, min(max_frames, frame_count)
            )
            if "fps" in param_mapping:
                payload["input"][param_mapping["fps"]] = resolved_fps
        elif model.startswith("kwaivgi/kling-"):
            payload["input"][duration_key] = 5 if seconds <= 5 else 10
        else:
            payload["input"][duration_key] = seconds

    if "resolution" in param_mapping:
        mapped_resolution_key = param_mapping["resolution"]
        if model.startswith("kwaivgi/kling-"):
            payload["input"].setdefault("mode", "standard")
            if resolution == "1080p":
                payload["input"]["mode"] = "pro"
                payload["input"][mapped_resolution_key] = "16:9"
            elif resolution == "1024p":
                payload["input"][mapped_resolution_key] = "16:9"
            else:
                payload["input"][mapped_resolution_key] = "1:1"
        elif model.startswith("bytedance/seedance-1-"):
            if resolution in {"480p", "720p", "1080p"}:
                payload["input"][mapped_resolution_key] = resolution
            elif resolution == "1024p":
                payload["input"][mapped_resolution_key] = "1080p"
            else:
                payload["input"][mapped_resolution_key] = "720p"
        else:
            payload["input"][mapped_resolution_key] = resolution

    if "audio_url" in param_mapping and audio_url:
        payload["input"][param_mapping["audio_url"]] = audio_url
    if fps is not None and "fps" in param_mapping:
        payload["input"][param_mapping["fps"]] = fps

    return payload


async def elevenlabs_tts_bytes(text: str, voice_id: str) -> bytes:
    """Generate speech with ElevenLabs and return it as raw bytes.

    Args:
        text: Script to synthesize.
        voice_id: Identifier of the ElevenLabs voice to use.

    Raises:
        HTTPException: If the API key is missing, the text is too long or the
            API responds with an error.
    """

    if not ELEVEN_API_KEY:
        raise HTTPException(500, "ELEVEN_API_KEY not set")
    if len(text) > TTS_MAX_CHARS:
        raise HTTPException(
            400,
            f"Text too long (max {TTS_MAX_CHARS} chars). Please shorten.",
        )

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            url,
            headers={
                "xi-api-key": ELEVEN_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "output_format": TTS_OUTPUT_FORMAT,
            },
        )
        r.raise_for_status()
        audio = r.content
        if len(audio) > 9_500_000:
            raise HTTPException(
                400,
                "Generated audio >9.5MB. Shorten script or reduce bitrate.",
            )
        return audio


async def supabase_upload(
    file_bytes: bytes, object_path: str, content_type: str
) -> str:
    """Upload a file to Supabase Storage and return a public URL."""

    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE:
        raise HTTPException(500, "Supabase env not set")
    upload_url = f"{UPLOAD_BASE}/{SUPABASE_BUCKET}/{object_path}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE}",
        "apikey": SUPABASE_SERVICE_ROLE,
        "Content-Type": content_type,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            upload_url,
            headers=headers,
            content=file_bytes,
            params={"upsert": "true"},
        )
        if r.status_code >= 400:
            raise HTTPException(
                r.status_code,
                f"Supabase upload failed: {r.text}",
            )
    return f"{PUBLIC_BASE}/{SUPABASE_BUCKET}/{object_path}?download=1"


async def supabase_delete(object_path: str) -> None:
    """Best-effort delete of a Supabase Storage object."""

    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE or not object_path:
        return

    delete_url = f"{UPLOAD_BASE}/{SUPABASE_BUCKET}/{object_path}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE}",
        "apikey": SUPABASE_SERVICE_ROLE,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            await client.delete(delete_url, headers=headers)
    except httpx.HTTPError:
        # Cleanup should not mask the originating exception.
        return


async def get_job_request(request_id: str) -> dict[str, Any] | None:
    """Fetch an idempotency record from Supabase by request id."""

    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE:
        raise HTTPException(500, "Supabase env not set")

    endpoint = f"{SUPABASE_URL}/rest/v1/job_requests"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE}",
        "apikey": SUPABASE_SERVICE_ROLE,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            endpoint,
            headers=headers,
            params={"request_id": f"eq.{request_id}", "select": "*", "limit": 1},
        )

    if response.status_code >= 400:
        raise HTTPException(
            response.status_code,
            f"Supabase idempotency lookup failed: {response.text}",
        )

    rows = response.json()
    return rows[0] if rows else None


async def create_job_request_processing(
    request_id: str, user_id: str | None, endpoint_name: str
) -> bool:
    """Attempt to claim an idempotent request id for processing."""

    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE:
        raise HTTPException(500, "Supabase env not set")

    endpoint = f"{SUPABASE_URL}/rest/v1/job_requests"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE}",
        "apikey": SUPABASE_SERVICE_ROLE,
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    payload = {
        "request_id": request_id,
        "user_id": user_id,
        "endpoint": endpoint_name,
        "status": "processing",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(endpoint, headers=headers, json=payload)

    if response.status_code in (200, 201):
        return True
    if response.status_code == 409:
        existing = await get_job_request(request_id)
        if not existing:
            raise HTTPException(
                409,
                "Conflicting request_id exists but could not be loaded. Retry with a new request_id.",
            )

        existing_endpoint = existing.get("endpoint")
        existing_user_id = existing.get("user_id")
        if existing_endpoint == endpoint_name and existing_user_id == user_id:
            return False

        raise HTTPException(
            409,
            "request_id already exists for a different endpoint or user scope. "
            "Use a new request_id.",
        )
        return False
    if response.status_code == 201 and response.text == "":
        return True
    if response.status_code == 204:
        return True
    if response.status_code >= 400:
        raise HTTPException(
            response.status_code,
            f"Supabase idempotency insert failed: {response.text}",
        )
    return False


async def update_job_request(
    request_id: str,
    status: str,
    response_payload: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """Persist idempotency completion state for an existing request.

    Expected Supabase schema: ``job_requests.response_payload`` and
    ``job_requests.error_payload`` (jsonb columns).
    """

    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE:
        raise HTTPException(500, "Supabase env not set")

    endpoint = f"{SUPABASE_URL}/rest/v1/job_requests"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE}",
        "apikey": SUPABASE_SERVICE_ROLE,
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    payload: dict[str, Any] = {"status": status}
    if response_payload is not None:
        payload["response_payload"] = response_payload
        payload["response_status"] = 200
    if error is not None:
        payload["error_payload"] = {"message": error}
        payload["response_status"] = 500

    async with httpx.AsyncClient(timeout=30) as client:
        patch_response = await client.patch(
            endpoint,
            headers=headers,
            params={"request_id": f"eq.{request_id}"},
            json=payload,
        )

    if patch_response.status_code >= 400:
        raise HTTPException(
            patch_response.status_code,
            f"Supabase idempotency update failed: {patch_response.text}",
        )


async def update_job_request_best_effort(
    request_id: str,
    status: str,
    response_payload: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """Persist idempotency state while preserving the original request outcome."""

    try:
        await update_job_request(
            request_id,
            status,
            response_payload=response_payload,
            error=error,
        )
    except Exception:
        logger.exception(
            "idempotency_update_failed request_id=%s status=%s",
            request_id,
            status,
        )


async def await_existing_job_request(request_id: str) -> dict[str, Any]:
    """Wait for a processing idempotent request to finish and return stored response."""

    elapsed = 0.0
    while elapsed <= IDEMPOTENCY_MAX_WAIT_SEC:
        row = await get_job_request(request_id)
        if not row:
            raise HTTPException(
                409, "Existing request not found. Please retry with a new request_id."
            )

        status = row.get("status")
        if status == "succeeded" and row.get("response_payload"):
            return row["response_payload"]
        if status == "failed":
            error_payload = row.get("error_payload")
            if isinstance(error_payload, dict):
                error_message = error_payload.get("message") or str(error_payload)
            else:
                error_message = str(error_payload) if error_payload else None
            raise HTTPException(
                409,
                error_message or "Request previously failed for this request_id.",
            )
        if status != "processing":
            raise HTTPException(409, f"Unexpected idempotency status '{status}'.")

        await asyncio.sleep(IDEMPOTENCY_POLL_INTERVAL_SEC)
        elapsed += IDEMPOTENCY_POLL_INTERVAL_SEC

    raise HTTPException(409, "Request already in progress, try again later.")


def _normalize_request_id(request_id: str | None) -> str | None:
    """Return normalized UUID string for idempotency keys, else None."""

    if not request_id:
        return None
    try:
        return str(uuid.UUID(request_id))
    except (ValueError, TypeError, AttributeError):
        logger.warning(
            "Ignoring invalid request_id for idempotency",
            extra={"request_id": request_id},
        )
        return None


async def insert_pet_video(
    *,
    user_id: str | None,
    video_url: str,
    image_url: str,
    script: str | None,
    prompt: str,
    voice_id: str | None,
    resolution: str,
    duration: int,
    model: str,
    created_at: datetime | None = None,
) -> None:
    """Persist a generated pet video record via Supabase PostgREST.

    Supabase's current schema omits the previous ``storage_key`` column, so we
    only persist the public ``video_url`` alongside the other metadata fields,
    including the resolved Replicate ``model`` used for generation.
    """

    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE:
        raise HTTPException(500, "Supabase env not set")

    created_at = created_at or datetime.now(timezone.utc)

    endpoint = f"{SUPABASE_URL}/rest/v1/pet_videos"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE}",
        "apikey": SUPABASE_SERVICE_ROLE,
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    payload = {
        "user_id": user_id,
        "video_url": video_url,
        "image_url": image_url,
        "script": script,
        "prompt": prompt,
        "voice_id": voice_id,
        "resolution": resolution,
        "duration": duration,
        "model": model,
        "created_at": created_at.isoformat(),
    }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(endpoint, headers=headers, json=payload)

    if response.status_code >= 400:
        raise HTTPException(
            response.status_code,
            f"Supabase metadata insert failed: {response.text}",
        )


def resolve_user_storage_prefix(user_context: UserContext | None) -> str:
    """Return a sanitized storage prefix for the provided user context."""

    if not user_context:
        return "anonymous"
    try:
        user_uuid = uuid.UUID(user_context.id)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(400, "user_context.id must be a valid UUID") from exc
    return f"users/{user_uuid}"  # uuid.UUID normalizes the string format


def build_storage_key(prefix: str, category: str, extension: str) -> str:
    """Construct a Supabase object key scoped to the user prefix."""

    safe_prefix = prefix.strip("/") or "anonymous"
    safe_prefix = safe_prefix.replace("..", "")
    return f"{safe_prefix}/{category}/{uuid.uuid4()}.{extension}"


async def fetch_binary(
    url: str,
    timeout: int = 300,
    max_bytes: int | None = FETCH_MAX_BYTES,
    *,
    allow_private: bool = ALLOW_PRIVATE_URL_FETCHES,
) -> bytes:
    """Download binary content from a remote URL with SSRF and size guards."""

    if max_bytes is not None and max_bytes <= 0:
        raise HTTPException(500, "FETCH_MAX_BYTES must be greater than zero.")

    current_url = url
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for _ in range(MAX_REDIRECT_HOPS + 1):
            _validate_outbound_url(current_url, allow_private=allow_private)

            async with client.stream("GET", current_url) as response:
                if response.is_redirect:
                    redirect_location = response.headers.get("location")
                    if not redirect_location:
                        raise HTTPException(
                            502, "Redirect response missing Location header."
                        )
                    current_url = urljoin(str(response.url), redirect_location)
                    continue

                response.raise_for_status()

                if max_bytes is not None:
                    declared_size = response.headers.get("content-length")
                    if declared_size:
                        try:
                            declared_bytes = int(declared_size)
                        except (TypeError, ValueError):
                            declared_bytes = None
                        if declared_bytes is not None and declared_bytes > max_bytes:
                            raise HTTPException(
                                413,
                                f"Remote file is too large ({declared_size} bytes > {max_bytes}).",
                            )

                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    if not chunk:
                        continue
                    total += len(chunk)
                    if max_bytes is not None and total > max_bytes:
                        raise HTTPException(
                            413,
                            f"Remote file exceeded {max_bytes} bytes while downloading.",
                        )
                    chunks.append(chunk)
                return b"".join(chunks)

    raise HTTPException(400, f"Too many redirects (max {MAX_REDIRECT_HOPS}).")


async def head_info(url: str) -> Tuple[int, str, int]:
    """Retrieve basic HTTP header information for a URL."""

    current_url = url
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as c:
        for _ in range(MAX_REDIRECT_HOPS + 1):
            _validate_outbound_url(current_url, allow_private=ALLOW_PRIVATE_URL_FETCHES)

            r = await c.head(current_url)
            if r.is_redirect:
                redirect_location = r.headers.get("location")
                if not redirect_location:
                    raise HTTPException(
                        502, "Redirect response missing Location header."
                    )
                current_url = urljoin(str(r.url), redirect_location)
                continue

            if r.status_code >= HTTPStatus.BAD_REQUEST:
                r = await c.get(current_url, headers={"Range": "bytes=0-1"})
            size = int(r.headers.get("content-length", "0"))
            return r.status_code, r.headers.get("content-type", ""), size

    raise HTTPException(400, f"Too many redirects (max {MAX_REDIRECT_HOPS}).")


def inspect_video_bytes(video_bytes: bytes) -> dict[str, Any]:
    """Inspect MP4 bytes using ffprobe to surface codec/container issues."""

    tmpdir = tempfile.mkdtemp()
    in_path = os.path.join(tmpdir, "inspect.mp4")
    try:
        with open(in_path, "wb") as infile:
            infile.write(video_bytes)

        ffprobe_cmd = [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            in_path,
        ]
        result = subprocess.run(
            ffprobe_cmd,
            check=True,
            capture_output=True,
            text=True,
        )
        parsed = json.loads(result.stdout)
        streams = parsed.get("streams", [])
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
        audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})
        return {
            "is_valid_mp4": bool(parsed.get("format")),
            "container": parsed.get("format", {}).get("format_name"),
            "duration": parsed.get("format", {}).get("duration"),
            "size": parsed.get("format", {}).get("size"),
            "video_codec": video_stream.get("codec_name"),
            "audio_codec": audio_stream.get("codec_name"),
            "width": video_stream.get("width"),
            "height": video_stream.get("height"),
        }
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        json.JSONDecodeError,
    ) as exc:
        return {"is_valid_mp4": False, "probe_error": type(exc).__name__}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


async def collect_video_delivery_debug(url: str) -> dict[str, Any]:
    """Collect download diagnostics for a final video URL."""

    status, content_type, content_length = await head_info(url)
    diagnostics: dict[str, Any] = {
        "head_status": status,
        "content_type": content_type,
        "content_length": content_length,
    }

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            partial = await client.get(url, headers={"Range": "bytes=0-1023"})
        diagnostics["range_status"] = partial.status_code
        diagnostics["accept_ranges"] = partial.headers.get("accept-ranges", "")
        diagnostics["content_range"] = partial.headers.get("content-range", "")
    except httpx.HTTPError as exc:
        diagnostics["range_error"] = type(exc).__name__

    return diagnostics


def _raise_final_video_error(
    message: str,
    *,
    final_url: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Raise a user-safe HTTP error while logging actionable debug metadata."""

    payload = {"message": message}
    if final_url:
        payload["final_url"] = final_url
    if details:
        payload["details"] = details

    logger.error("final_video_issue=%s", payload)
    raise HTTPException(
        502,
        "Final video could not be validated for playback. Use /debug/final_video for details.",
    )


async def replicate_video_from_prompt(
    model: str,
    image_url: str,
    prompt: str,
    seconds: int,
    resolution: str,
    audio_url: str = None,
    fps: int | None = None,
    input_params: dict[str, Any] | None = None,
) -> str:
    """Create a video using a specified Replicate model."""

    if not REPLICATE_API_TOKEN:
        raise HTTPException(500, "Replicate API token not set")

    # Validate model and build payload
    payload = build_model_payload(
        model, image_url, prompt, seconds, resolution, audio_url, fps, input_params
    )

    headers = {
        "Authorization": f"Token {REPLICATE_API_TOKEN}",
        "Content-Type": "application/json",
    }

    create_url = f"https://api.replicate.com/v1/models/{model}/predictions"

    async with httpx.AsyncClient(timeout=600) as client:
        create = await client.post(create_url, headers=headers, json=payload)
        if create.status_code >= 400:
            raise HTTPException(
                create.status_code,
                f"Replicate {model} create failed: {create.text}",
            )
        pred = create.json()
        pred_id = pred.get("id")
        if not pred_id:
            raise HTTPException(500, "Replicate missing prediction id")

        poll_started_at = time.monotonic()
        while True:
            elapsed = time.monotonic() - poll_started_at
            if elapsed > REPLICATE_POLL_TIMEOUT_SEC:
                raise HTTPException(
                    504,
                    (
                        "Replicate prediction timed out before completion "
                        f"(prediction_id={pred_id})."
                    ),
                )

            getr = await client.get(
                f"https://api.replicate.com/v1/predictions/{pred_id}",
                headers=headers,
            )
            getr.raise_for_status()
            data = getr.json()
            status = data.get("status")
            if status in ("succeeded", "failed", "canceled"):
                if status != "succeeded":
                    raise HTTPException(
                        400,
                        (
                            f"{model} {status}: {data.get('error')} | "
                            f"logs: {data.get('logs')}"
                        ),
                    )
                output = data.get("output")
                if isinstance(output, list) and output:
                    return output[-1]
                if isinstance(output, str):
                    return output
                raise HTTPException(500, "Replicate missing output URL")
            await asyncio.sleep(REPLICATE_POLL_INTERVAL_SEC)


async def generate_video_from_prompt(
    model: str,
    image_url: str,
    prompt: str,
    seconds: int,
    resolution: str,
    audio_url: str = None,
    fps: int | None = None,
    input_params: dict[str, Any] | None = None,
) -> str:
    """Create a talking-pet style video using the specified Replicate model."""

    return await replicate_video_from_prompt(
        model, image_url, prompt, seconds, resolution, audio_url, fps, input_params
    )


def _build_mux_command(
    ffmpeg_path: str, video_path: str, audio_path: str, output_path: str
) -> list[str]:
    """Build ffmpeg command arguments for deterministic video/audio stream mapping."""

    return [
        ffmpeg_path,
        "-y",
        "-i",
        video_path,
        "-i",
        audio_path,
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-af",
        # add 0.6s delay to audio start and 0.6s outro buffer
        "adelay=600|600,apad=pad_dur=0.6",
        "-shortest",
        output_path,
    ]


@lru_cache(maxsize=1)
def get_ffmpeg_path() -> str:
    """Resolve an ffmpeg binary path and validate it is runnable."""

    ffmpeg_path = None
    try:
        imageio_ffmpeg = importlib.import_module("imageio_ffmpeg")
    except Exception as exc:  # pragma: no cover - fallback path in production
        warning = "imageio_ffmpeg import failed; falling back to PATH ffmpeg: %s"
        if "pkg_resources" in str(exc):
            warning += " (hint: install setuptools to provide pkg_resources)"
        logger.warning(warning, str(exc))
    else:
        try:
            ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        except (AttributeError, OSError, RuntimeError, ValueError) as exc:
            logger.warning(
                "imageio_ffmpeg.get_ffmpeg_exe failed; falling back to PATH ffmpeg: %s",
                str(exc),
            )

    if not ffmpeg_path:
        ffmpeg_path = shutil.which("ffmpeg")

    if not ffmpeg_path:
        logger.error("ffmpeg binary not found via imageio_ffmpeg or PATH")
        raise HTTPException(500, "ffmpeg not available in runtime")

    try:
        subprocess.run(
            [ffmpeg_path, "-version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as exc:
        logger.error("ffmpeg binary not found (path=%s)", ffmpeg_path)
        raise HTTPException(500, "ffmpeg not available in runtime") from exc
    except subprocess.CalledProcessError as exc:
        logger.error(
            "ffmpeg -version failed (path=%s, stderr=%s)",
            ffmpeg_path,
            (exc.stderr or "").strip(),
        )
        raise HTTPException(500, "ffmpeg not available in runtime") from exc

    logger.info("Using ffmpeg binary at path=%s", ffmpeg_path)
    return ffmpeg_path


def run_ffmpeg_runtime_smoke_check() -> None:
    """Log ffmpeg availability during startup so runtime issues surface earlier."""

    try:
        ffmpeg_path = get_ffmpeg_path()
    except HTTPException:
        logger.warning(
            "ffmpeg runtime smoke check failed; install setuptools (for pkg_resources) and ensure ffmpeg is on PATH"
        )
    except Exception as exc:  # pragma: no cover - defensive startup guard
        logger.warning(
            "ffmpeg runtime smoke check failed with unexpected error; ensure ffmpeg binary is executable and available (%s)",
            str(exc),
        )
    else:
        logger.info("ffmpeg runtime smoke check passed (path=%s)", ffmpeg_path)


@app.on_event("startup")
async def startup_runtime_checks() -> None:
    """Run startup-time runtime checks."""

    run_ffmpeg_runtime_smoke_check()


async def mux_video_audio(video_url: str, audio_url: str) -> bytes:
    """Combine a video and an audio track into a single MP4 file."""

    tmpdir = tempfile.mkdtemp()
    vpath = os.path.join(tmpdir, "in.mp4")
    apath = os.path.join(tmpdir, "in.mp3")
    fpath = os.path.join(tmpdir, "out.mp4")

    try:
        async with httpx.AsyncClient() as client:
            vr = await client.get(video_url)
            vr.raise_for_status()
            with open(vpath, "wb") as f:
                f.write(vr.content)
            ar = await client.get(audio_url)
            ar.raise_for_status()
            with open(apath, "wb") as f:
                f.write(ar.content)

        ffmpeg_path = get_ffmpeg_path()
        cmd = _build_mux_command(ffmpeg_path, vpath, apath, fpath)
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

        with open(fpath, "rb") as outfile:
            final_bytes = outfile.read()
        return final_bytes
    except FileNotFoundError as exc:
        logger.error("ffmpeg executable not found during mux")
        raise HTTPException(500, "ffmpeg not available in runtime") from exc
    except subprocess.CalledProcessError as exc:
        logger.error("ffmpeg mux failed: %s", (exc.stderr or "").strip())
        raise HTTPException(500, "ffmpeg mux failed") from exc
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _compress_video_bytes(video_bytes: bytes, crf: int) -> bytes:
    """Re-encode MP4 bytes with H.264/AAC using a configurable CRF value."""

    tmpdir = tempfile.mkdtemp()
    in_path = os.path.join(tmpdir, "in.mp4")
    out_path = os.path.join(tmpdir, "out.mp4")

    try:
        with open(in_path, "wb") as infile:
            infile.write(video_bytes)

        ffmpeg_path = get_ffmpeg_path()
        commands = [
            [
                ffmpeg_path,
                "-y",
                "-i",
                in_path,
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                str(crf),
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                out_path,
            ],
            [
                ffmpeg_path,
                "-y",
                "-i",
                in_path,
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-c:v",
                "mpeg4",
                "-q:v",
                str(max(6, min(31, int(crf / 3)))),
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                out_path,
            ],
        ]

        last_error: subprocess.CalledProcessError | None = None
        for cmd in commands:
            try:
                subprocess.run(
                    cmd,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                with open(out_path, "rb") as outfile:
                    return outfile.read()
            except subprocess.CalledProcessError as exc:
                last_error = exc
                encoder_name = "unknown"
                if "-c:v" in cmd:
                    encoder_name = cmd[cmd.index("-c:v") + 1]
                logger.warning(
                    "video compression attempt failed encoder=%s stderr=%s",
                    encoder_name,
                    (exc.stderr or "").strip(),
                )

        if last_error is not None:
            raise last_error
        raise RuntimeError("video compression command unexpectedly produced no result")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def prepare_video_for_upload_with_debug(
    video_bytes: bytes,
) -> tuple[bytes, dict[str, Any]]:
    """Compress video bytes if needed and return both payload + debug metadata."""

    limit = VIDEO_UPLOAD_TARGET_BYTES
    attempts: list[dict[str, Any]] = []

    if len(video_bytes) <= limit:
        return (
            video_bytes,
            {
                "target_bytes": limit,
                "original_bytes": len(video_bytes),
                "final_bytes": len(video_bytes),
                "already_within_target": True,
                "meets_target": True,
                "attempts": attempts,
            },
        )

    best = video_bytes
    for crf in (28, 32, 36):
        try:
            compressed = _compress_video_bytes(best, crf)
        except subprocess.CalledProcessError as exc:
            attempts.append({"crf": crf, "error": type(exc).__name__})
            raise HTTPException(
                500,
                "Failed to compress generated video before upload.",
            ) from exc

        improved = len(compressed) < len(best)
        attempts.append(
            {
                "crf": crf,
                "output_bytes": len(compressed),
                "improved": improved,
            }
        )
        if improved:
            best = compressed
        if len(best) <= limit:
            return (
                best,
                {
                    "target_bytes": limit,
                    "original_bytes": len(video_bytes),
                    "final_bytes": len(best),
                    "already_within_target": False,
                    "meets_target": True,
                    "attempts": attempts,
                },
            )

    max_mb = limit / (1024 * 1024)
    actual_mb = len(best) / (1024 * 1024)
    raise HTTPException(
        400,
        (
            "Generated video is too large for storage upload even after compression "
            f"({actual_mb:.1f}MB > {max_mb:.1f}MB target). "
            "Try fewer seconds, lower resolution, or increase VIDEO_UPLOAD_TARGET_BYTES "
            "if your Supabase project allows larger objects."
        ),
    )


def analyze_video_compression(
    video_bytes: bytes,
    *,
    target_bytes: int | None = None,
) -> dict[str, Any]:
    """Run compression-analysis attempts for debugging a video payload."""

    if target_bytes is None or target_bytes == VIDEO_UPLOAD_TARGET_BYTES:
        _, debug = prepare_video_for_upload_with_debug(video_bytes)
        return debug

    limit = target_bytes
    attempts: list[dict[str, Any]] = []
    best = video_bytes

    if len(video_bytes) <= limit:
        return {
            "target_bytes": limit,
            "original_bytes": len(video_bytes),
            "final_bytes": len(video_bytes),
            "already_within_target": True,
            "meets_target": True,
            "attempts": attempts,
        }

    for crf in (28, 32, 36):
        try:
            compressed = _compress_video_bytes(best, crf)
        except subprocess.CalledProcessError as exc:
            attempts.append({"crf": crf, "error": type(exc).__name__})
            return {
                "target_bytes": limit,
                "original_bytes": len(video_bytes),
                "final_bytes": len(best),
                "already_within_target": False,
                "meets_target": False,
                "attempts": attempts,
            }

        improved = len(compressed) < len(best)
        attempts.append(
            {
                "crf": crf,
                "output_bytes": len(compressed),
                "improved": improved,
            }
        )
        if improved:
            best = compressed
        if len(best) <= limit:
            break

    return {
        "target_bytes": limit,
        "original_bytes": len(video_bytes),
        "final_bytes": len(best),
        "already_within_target": False,
        "meets_target": len(best) <= limit,
        "attempts": attempts,
    }


def prepare_video_for_upload(video_bytes: bytes) -> bytes:
    """Ensure MP4 payloads fit the configured upload target size."""

    upload_ready_bytes, _ = prepare_video_for_upload_with_debug(video_bytes)
    return upload_ready_bytes


# ===== Routes =====
@app.get("/health")
async def health():
    """Simple health check used by deployment platforms."""
    return {"ok": True}


@app.get("/models")
async def list_supported_models(_: None = Depends(require_auth)):
    """List all supported i2v models and routing metadata."""

    def _serialize_tunable_params(
        tunable_params: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        transformed_params: list[dict[str, Any]] = []
        for tunable_param in tunable_params:
            transformed_param = tunable_param.copy()
            if "help" in transformed_param and "description" not in transformed_param:
                transformed_param["description"] = transformed_param["help"]
            transformed_params.append(transformed_param)
        return transformed_params

    models = {}
    for model_id, config in SUPPORTED_MODELS.items():
        models[model_id] = {
            "name": config["name"],
            "tier": config["tier"],
            "quality_label": config["quality_label"],
            "blurb": config["blurb"],
            "capabilities": config["capabilities"],
            "tunable_params": _serialize_tunable_params(
                config.get("tunable_params", [])
            ),
            "supported_durations": config.get("supported_durations", []),
            "supported_fps": config.get("supported_fps", []),
            "supported_resolutions": config.get("supported_resolutions", []),
            "min_plan_tier": config.get("min_plan_tier", "free"),
            "runnable": config.get("runnable", True),
            "is_default": model_id == DEFAULT_MODEL,
        }
    return {
        "supported_models": models,
        "default_model": DEFAULT_MODEL,
        "routing_defaults": VIDEO_MODEL_ROUTES,
    }


@app.post("/resolve_model")
async def resolve_model(req: ModelIntentRequest, _: None = Depends(require_auth)):
    """Resolve model selection from high-level user intent."""

    normalized_quality = normalize_quality(req.quality)
    override = req.model_override
    intent = to_model_dict(req)
    intent["quality"] = normalized_quality

    plan_tier = await resolve_plan_tier(
        to_model_dict(req.user_context) if req.user_context else None,
        SUPABASE_URL,
        SUPABASE_SERVICE_ROLE,
    )
    intent["plan_tier"] = plan_tier

    if override:
        try:
            model = resolve_explicit_video_model(override)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not is_model_allowed_for_plan(model, plan_tier):
            required = get_model_min_plan_tier(model).capitalize()
            raise HTTPException(
                403,
                f"This model requires {required}. Your plan is {plan_tier.capitalize()}.",
            )

        config = get_model_config(model)
        resolved_settings = _resolve_generation_settings(
            model_slug=model,
            config=config,
            seconds=req.seconds,
            resolution=req.resolution,
            fps=req.fps,
            quality=normalized_quality,
            plan_tier=plan_tier,
        )
        meta = {
            "name": config["name"],
            "tier": config["tier"],
            "quality_label": config["quality_label"],
            "blurb": config["blurb"],
            "supported_durations": config.get("supported_durations", []),
            "supported_fps": config.get("supported_fps", []),
            "supported_resolutions": config.get("supported_resolutions", []),
            "tunable_params": config.get("tunable_params", []),
            "min_plan_tier": config.get("min_plan_tier", "free"),
            "runnable": config.get("runnable", True),
            "plan_tier": plan_tier,
        }
        return {
            "model": model,
            "resolved_model_slug": model,
            "plan_tier": plan_tier,
            "meta": meta,
            "resolved": {**resolved_settings},
        }

    try:
        resolved = await resolve_model_for_intent(intent)
    except ValueError as exc:
        raise HTTPException(
            400,
            f"Unable to resolve model settings: {exc}",
        ) from exc
    effective_plan_tier = resolved.get(
        "plan_tier", resolved["resolved_meta"].get("plan_tier")
    )
    return {
        "model": resolved["resolved_model_slug"],
        "resolved_model_slug": resolved["resolved_model_slug"],
        "plan_tier": effective_plan_tier,
        "meta": resolved["resolved_meta"],
        "resolved": resolved["resolved"],
    }


async def _resolve_job_model(
    *,
    seconds: int,
    resolution: str,
    quality: str,
    fps: int | None,
    has_audio: bool,
    user_context: UserContext | None,
    model: str | None,
    model_override: str | None,
    model_params: dict[str, Any] | None,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    normalized_quality = normalize_quality(quality)
    override = model_override or model
    plan_tier = await resolve_plan_tier(
        to_model_dict(user_context) if user_context else None,
        SUPABASE_URL,
        SUPABASE_SERVICE_ROLE,
    )

    if override:
        try:
            chosen = resolve_explicit_video_model(override)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not is_model_allowed_for_plan(chosen, plan_tier):
            required = get_model_min_plan_tier(chosen).capitalize()
            raise HTTPException(
                403,
                f"This model requires {required}. Your plan is {plan_tier.capitalize()}.",
            )
        config = get_model_config(chosen)
        resolved = _resolve_generation_settings(
            model_slug=chosen,
            config=config,
            seconds=seconds,
            resolution=resolution,
            fps=fps,
            quality=normalized_quality,
            plan_tier=plan_tier,
        )
    else:
        try:
            result = await resolve_model_for_intent(
                {
                    "seconds": seconds,
                    "resolution": resolution,
                    "quality": normalized_quality,
                    "fps": fps,
                    "has_audio": has_audio,
                    "plan_tier": plan_tier,
                    "user_context": (
                        to_model_dict(user_context) if user_context else None
                    ),
                }
            )
        except ValueError as exc:
            raise HTTPException(
                400,
                f"Unable to resolve model settings: {exc}",
            ) from exc
        chosen = result["resolved_model_slug"]
        if not is_model_allowed_for_plan(chosen, plan_tier):
            raise HTTPException(
                500,
                "Routing misconfiguration: selected model is not allowed for this plan.",
            )
        config = get_model_config(chosen)
        resolved = result["resolved"]

    if not has_audio and chosen == "wan-video/wan-2.2-s2v":
        raise HTTPException(
            400,
            "wan-video/wan-2.2-s2v is a speech-to-video model that requires audio. "
            "Use /jobs_prompt_tts endpoint instead.",
        )

    params = config.get("default_params", {}).copy()
    params.update(apply_allowed_model_params(chosen, model_params))
    if resolved.get("fps") is not None and "fps" in config.get("param_mapping", {}):
        params["fps"] = resolved["fps"]

    return chosen, params, resolved


@app.post("/jobs_prompt_only")
async def create_job_with_prompt(req: JobPromptOnly, _: None = Depends(require_auth)):
    """Generate a video from a static image and text prompt."""
    normalized_request_id = _normalize_request_id(req.request_id)
    user_id = req.user_context.id if req.user_context else None
    _validate_outbound_url(req.image_url, allow_private=ALLOW_PRIVATE_URL_FETCHES)

    model, input_params, resolved = await _resolve_job_model(
        seconds=req.seconds,
        resolution=req.resolution,
        quality=req.quality,
        fps=req.fps,
        has_audio=False,
        user_context=req.user_context,
        model=req.model,
        model_override=req.model_override,
        model_params=req.model_params,
    )
    prefix = resolve_user_storage_prefix(req.user_context)

    if normalized_request_id:
        owner = await create_job_request_processing(
            normalized_request_id, user_id, "/jobs_prompt_only"
        )
        logger.info(
            "idempotency_request endpoint=/jobs_prompt_only request_id=%s owner=%s",
            normalized_request_id,
            owner,
        )
        if not owner:
            existing_response = await await_existing_job_request(normalized_request_id)
            logger.info(
                "idempotency_request endpoint=/jobs_prompt_only request_id=%s owner=false deduped=true",
                normalized_request_id,
            )
            return existing_response

    try:
        video_url = await generate_video_from_prompt(
            model,
            req.image_url,
            req.prompt,
            resolved["seconds"],
            resolved["resolution"],
            fps=resolved.get("fps"),
            input_params=input_params,
        )
        video_bytes = await fetch_binary(video_url)
        upload_ready_bytes, compression_debug = prepare_video_for_upload_with_debug(
            video_bytes
        )
        final_key = build_storage_key(prefix, "videos", "mp4")
        final_url = await supabase_upload(upload_ready_bytes, final_key, "video/mp4")

        try:
            if ENABLE_FINAL_VIDEO_DEBUG:
                diagnostics = await collect_video_delivery_debug(final_url)
                if compression_debug is not None:
                    diagnostics["compression"] = compression_debug
                if diagnostics.get("head_status", 0) >= 400:
                    _raise_final_video_error(
                        "Uploaded final video URL is not publicly reachable.",
                        final_url=final_url,
                        details=diagnostics,
                    )
                if diagnostics.get("content_length", 0) <= 0:
                    _raise_final_video_error(
                        "Uploaded final video appears empty.",
                        final_url=final_url,
                        details=diagnostics,
                    )

            await insert_pet_video(
                user_id=user_id,
                video_url=final_url,
                image_url=req.image_url,
                script=None,
                prompt=req.prompt,
                voice_id=None,
                resolution=resolved["resolution"],
                duration=resolved["seconds"],
                model=model,
            )
        except HTTPException:
            await supabase_delete(final_key)
            raise
        except Exception:
            await supabase_delete(final_key)
            raise

        response_payload = {"video_url": video_url, "final_url": final_url}
        if normalized_request_id:
            await update_job_request_best_effort(
                normalized_request_id,
                "succeeded",
                response_payload=response_payload,
                error=None,
            )
        return response_payload
    except HTTPException as exc:
        if normalized_request_id:
            await update_job_request_best_effort(
                normalized_request_id,
                "failed",
                error=str(exc.detail),
            )
        raise
    except Exception as exc:
        _log_unexpected_job_error(
            endpoint="/jobs_prompt_only",
            exc=exc,
            model=model,
            request_id=normalized_request_id,
            user_id=user_id,
        )
        if normalized_request_id:
            await update_job_request_best_effort(
                normalized_request_id,
                "failed",
                error="Unexpected server error while processing this request_id.",
            )
        raise exc


@app.post("/jobs_prompt_tts")
async def create_job_with_prompt_and_tts(
    req: JobPromptTTS, _: None = Depends(require_auth)
):
    """Generate a video with synchronized speech."""
    normalized_request_id = _normalize_request_id(req.request_id)
    user_id = req.user_context.id if req.user_context else None
    _validate_outbound_url(req.image_url, allow_private=ALLOW_PRIVATE_URL_FETCHES)

    model, input_params, resolved = await _resolve_job_model(
        seconds=req.seconds,
        resolution=req.resolution,
        quality=req.quality,
        fps=req.fps,
        has_audio=True,
        user_context=req.user_context,
        model=req.model,
        model_override=req.model_override,
        model_params=req.model_params,
    )
    prefix = resolve_user_storage_prefix(req.user_context)

    if normalized_request_id:
        owner = await create_job_request_processing(
            normalized_request_id, user_id, "/jobs_prompt_tts"
        )
        logger.info(
            "idempotency_request endpoint=/jobs_prompt_tts request_id=%s owner=%s",
            normalized_request_id,
            owner,
        )
        if not owner:
            existing_response = await await_existing_job_request(normalized_request_id)
            logger.info(
                "idempotency_request endpoint=/jobs_prompt_tts request_id=%s owner=false deduped=true",
                normalized_request_id,
            )
            return existing_response

    final_key: str | None = None
    audio_key: str | None = None

    try:
        mp3_bytes = await elevenlabs_tts_bytes(req.text, req.voice_id)
        audio_key = build_storage_key(prefix, "audio", "mp3")
        audio_public_url = await supabase_upload(mp3_bytes, audio_key, "audio/mpeg")

        final_url: str | None = None
        video_url: str | None = None

        if get_model_config(model)["capabilities"].get("supportsAudioIn"):
            video_url = await generate_video_from_prompt(
                model,
                req.image_url,
                req.prompt,
                resolved["seconds"],
                resolved["resolution"],
                audio_public_url,
                resolved.get("fps"),
                input_params,
            )
            final_key = build_storage_key(prefix, "videos", "mp4")
            final_bytes = await fetch_binary(video_url)
            upload_ready_bytes, _compression_debug = (
                prepare_video_for_upload_with_debug(final_bytes)
            )
            final_url = await supabase_upload(
                upload_ready_bytes, final_key, "video/mp4"
            )
        else:
            video_url = await generate_video_from_prompt(
                model,
                req.image_url,
                req.prompt,
                resolved["seconds"],
                resolved["resolution"],
                fps=resolved.get("fps"),
                input_params=input_params,
            )

            final_bytes = await mux_video_audio(video_url, audio_public_url)
            upload_ready_bytes, _compression_debug = (
                prepare_video_for_upload_with_debug(final_bytes)
            )
            final_key = build_storage_key(prefix, "videos", "mp4")
            final_url = await supabase_upload(
                upload_ready_bytes, final_key, "video/mp4"
            )

        if ENABLE_FINAL_VIDEO_DEBUG and final_url:
            diagnostics = await collect_video_delivery_debug(final_url)
            if diagnostics.get("head_status", 0) >= 400:
                _raise_final_video_error(
                    "Uploaded final video URL is not publicly reachable.",
                    final_url=final_url,
                    details=diagnostics,
                )
            if diagnostics.get("content_length", 0) <= 0:
                _raise_final_video_error(
                    "Uploaded final video appears empty.",
                    final_url=final_url,
                    details=diagnostics,
                )

        await insert_pet_video(
            user_id=user_id,
            video_url=final_url,
            image_url=req.image_url,
            script=req.text,
            prompt=req.prompt,
            voice_id=req.voice_id,
            resolution=resolved["resolution"],
            duration=resolved["seconds"],
            model=model,
        )

        response_payload = {
            "audio_url": audio_public_url,
            "video_url": video_url,
            "final_url": final_url,
        }
        if normalized_request_id:
            await update_job_request_best_effort(
                normalized_request_id,
                "succeeded",
                response_payload=response_payload,
                error=None,
            )

        return response_payload
    except HTTPException as exc:
        if final_key:
            await supabase_delete(final_key)
        if audio_key:
            await supabase_delete(audio_key)
        if normalized_request_id:
            await update_job_request_best_effort(
                normalized_request_id,
                "failed",
                error=str(exc.detail),
            )
        raise
    except Exception as exc:
        _log_unexpected_job_error(
            endpoint="/jobs_prompt_tts",
            exc=exc,
            model=model,
            request_id=normalized_request_id,
            user_id=user_id,
        )
        if final_key:
            await supabase_delete(final_key)
        if audio_key:
            await supabase_delete(audio_key)
        if normalized_request_id:
            await update_job_request_best_effort(
                normalized_request_id,
                "failed",
                error="Unexpected server error while processing this request_id.",
            )
        raise


# ===== Debug =====
@app.post("/debug/head")
async def debug_head(req: HeadRequest, _: None = Depends(require_auth)):
    """Fetch metadata about a URL without downloading the entire file."""
    status, ctype, size = await head_info(req.url)
    return {"status": status, "content_type": ctype, "bytes": size}


@app.post("/debug/final_video")
async def debug_final_video(
    req: FinalVideoDebugRequest, _: None = Depends(require_auth)
):
    """Inspect final video delivery and MP4 structure for troubleshooting."""

    diagnostics = await collect_video_delivery_debug(req.url)
    try:
        sample_bytes = await fetch_binary(
            req.url,
            timeout=60,
            max_bytes=DEBUG_FETCH_MAX_BYTES,
        )
    except httpx.HTTPError as exc:
        diagnostics["download_error"] = type(exc).__name__
        return {"final_url": req.url, "diagnostics": diagnostics}
    except HTTPException as exc:
        diagnostics["download_error"] = f"HTTPException:{exc.status_code}"
        diagnostics["download_error_detail"] = exc.detail
        return {"final_url": req.url, "diagnostics": diagnostics}

    diagnostics["probe"] = inspect_video_bytes(sample_bytes)
    diagnostics["downloaded_bytes"] = len(sample_bytes)

    if req.include_compression_debug:
        diagnostics["compression"] = analyze_video_compression(
            sample_bytes,
            target_bytes=req.target_bytes,
        )

    return {"final_url": req.url, "diagnostics": diagnostics}
