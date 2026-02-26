"""
Minimal FastAPI backend (cleaned) for Talking Pet MVP.
- ElevenLabs TTS + Replicate tiered model routing + Supabase uploads
- Keeps one debug helper: /debug/head to inspect public file headers
"""

import asyncio
import os
import secrets
import uuid
import tempfile
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any, Tuple

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from model_registry import (
    DEFAULT_MODEL,
    PROMPT_ONLY_FALLBACK_MODEL,
    SUPPORTED_MODELS,
    VIDEO_MODEL_ROUTES,
)
from model_routing import (
    apply_allowed_model_params,
    get_default_video_model,
    normalize_video_model,
    resolve_model_for_intent,
    normalize_quality,
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
class UserContext(BaseModel):
    """Authenticated user metadata forwarded by the studio frontend."""

    id: str
    email: str | None = None
    name: str | None = None
    plan_tier: str | None = None


class ModelIntentRequest(BaseModel):
    """High-level model routing intent used by automatic backend selection."""

    seconds: int = 6
    resolution: str = "768p"
    quality: str = "fast"
    fps: int | None = None
    has_audio: bool = False
    model_override: str | None = None
    model_params: dict[str, Any] | None = None
    user_context: UserContext | None = None


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


class HeadRequest(BaseModel):
    """Request body for the ``/debug/head`` endpoint."""

    url: str


def to_model_dict(model: BaseModel) -> dict[str, Any]:
    """Compat helper for pydantic v1/v2 model serialization."""

    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


# ===== Helpers =====


def _resolve_generation_settings(
    *,
    config: dict[str, Any],
    seconds: int,
    resolution: str,
    fps: int | None,
    quality: str,
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

    supported_resolutions = config.get("supported_resolutions", [])
    if resolution in supported_resolutions:
        resolved_resolution = resolution
    elif resolution in {"768p", "720p"} and "720p" in supported_resolutions:
        resolved_resolution = "720p"
    elif resolution in {"1024p", "1080p"} and "1080p" in supported_resolutions:
        resolved_resolution = "1080p"
    else:
        resolved_resolution = (
            supported_resolutions[0] if supported_resolutions else resolution
        )

    resolved_fps = fps if fps in config.get("supported_fps", []) else None

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
    return SUPPORTED_MODELS[model]


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

    if "image_url" in param_mapping:
        payload["input"][param_mapping["image_url"]] = image_url
    if "prompt" in param_mapping:
        payload["input"][param_mapping["prompt"]] = prompt
    if "seconds" in param_mapping:
        if model.startswith("kwaivgi/kling-"):
            payload["input"][param_mapping["seconds"]] = 5 if seconds <= 5 else 10
        else:
            payload["input"][param_mapping["seconds"]] = seconds
    if "resolution" in param_mapping:
        if model.startswith("kwaivgi/kling-"):
            payload["input"].setdefault("mode", "standard")
            if resolution == "1080p":
                payload["input"]["mode"] = "pro"
                payload["input"][param_mapping["resolution"]] = "16:9"
            elif resolution == "1024p":
                payload["input"][param_mapping["resolution"]] = "16:9"
            else:
                payload["input"][param_mapping["resolution"]] = "1:1"
        elif model.startswith("bytedance/seedance-1-"):
            if resolution in {"480p", "720p", "1080p"}:
                payload["input"][param_mapping["resolution"]] = resolution
            elif resolution == "1024p":
                payload["input"][param_mapping["resolution"]] = "1080p"
            else:
                payload["input"][param_mapping["resolution"]] = "720p"
        else:
            payload["input"][param_mapping["resolution"]] = resolution
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


async def fetch_binary(url: str, timeout: int = 300) -> bytes:
    """Download binary content from a remote URL."""

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content


async def head_info(url: str) -> Tuple[int, str, int]:
    """Retrieve basic HTTP header information for a URL."""

    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.head(url)
        if r.status_code >= 400:
            r = await c.get(url, headers={"Range": "bytes=0-1"})
        size = int(r.headers.get("content-length", "0"))
        return r.status_code, r.headers.get("content-type", ""), size


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

        while True:
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
            await asyncio.sleep(2)


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


async def mux_video_audio(video_url: str, audio_url: str) -> bytes:
    """Combine a video and an audio track into a single MP4 file."""

    tmpdir = tempfile.mkdtemp()
    vpath = os.path.join(tmpdir, "in.mp4")
    apath = os.path.join(tmpdir, "in.mp3")
    fpath = os.path.join(tmpdir, "out.mp4")

    async with httpx.AsyncClient() as client:
        vr = await client.get(video_url)
        vr.raise_for_status()
        with open(vpath, "wb") as f:
            f.write(vr.content)
        ar = await client.get(audio_url)
        ar.raise_for_status()
        with open(apath, "wb") as f:
            f.write(ar.content)

    import imageio_ffmpeg

    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg_path,
        "-y",
        "-i",
        vpath,
        "-i",
        apath,
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-af",
        # add 0.6s delay to audio start and 0.6s outro buffer
        "adelay=600|600,apad=pad_dur=0.6",
        "-shortest",
        fpath,
    ]
    subprocess.run(cmd, check=True)

    final_bytes = open(fpath, "rb").read()
    shutil.rmtree(tmpdir)
    return final_bytes


def _compress_video_bytes(video_bytes: bytes, crf: int) -> bytes:
    """Re-encode MP4 bytes with H.264/AAC using a configurable CRF value."""

    tmpdir = tempfile.mkdtemp()
    in_path = os.path.join(tmpdir, "in.mp4")
    out_path = os.path.join(tmpdir, "out.mp4")

    try:
        with open(in_path, "wb") as infile:
            infile.write(video_bytes)

        import imageio_ffmpeg

        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [
            ffmpeg_path,
            "-y",
            "-i",
            in_path,
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
        ]
        subprocess.run(cmd, check=True)

        with open(out_path, "rb") as outfile:
            return outfile.read()
    finally:
        shutil.rmtree(tmpdir)


def prepare_video_for_upload(video_bytes: bytes) -> bytes:
    """Ensure MP4 payloads fit the configured upload target size.

    Attempts progressively stronger compression when files exceed
    ``VIDEO_UPLOAD_TARGET_BYTES``.
    """

    if len(video_bytes) <= VIDEO_UPLOAD_TARGET_BYTES:
        return video_bytes

    best = video_bytes
    for crf in (28, 32, 36):
        try:
            compressed = _compress_video_bytes(best, crf)
        except subprocess.CalledProcessError as exc:
            raise HTTPException(
                500,
                "Failed to compress generated video before upload.",
            ) from exc

        if len(compressed) < len(best):
            best = compressed
        if len(best) <= VIDEO_UPLOAD_TARGET_BYTES:
            return best

    max_mb = VIDEO_UPLOAD_TARGET_BYTES / (1024 * 1024)
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


# ===== Routes =====
@app.get("/health")
async def health(_: None = Depends(require_auth)):
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

    if override:
        model = normalize_video_model(override)
        config = get_model_config(model)
        resolved_settings = _resolve_generation_settings(
            config=config,
            seconds=req.seconds,
            resolution=req.resolution,
            fps=req.fps,
            quality=normalized_quality,
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
        }
        return {
            "model": model,
            "resolved_model_slug": model,
            "meta": meta,
            "resolved": {**resolved_settings},
        }

    resolved = await resolve_model_for_intent(intent)
    return {
        "model": resolved["resolved_model_slug"],
        "resolved_model_slug": resolved["resolved_model_slug"],
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
    if override:
        chosen = normalize_video_model(override)
        config = get_model_config(chosen)
        resolved = _resolve_generation_settings(
            config=config,
            seconds=seconds,
            resolution=resolution,
            fps=fps,
            quality=normalized_quality,
        )
    else:
        result = await resolve_model_for_intent(
            {
                "seconds": seconds,
                "resolution": resolution,
                "quality": normalized_quality,
                "fps": fps,
                "has_audio": has_audio,
                "user_context": to_model_dict(user_context) if user_context else None,
            }
        )
        chosen = result["resolved_model_slug"]
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
    user_id = req.user_context.id if req.user_context else None

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
    upload_ready_bytes = prepare_video_for_upload(video_bytes)
    final_key = build_storage_key(prefix, "videos", "mp4")
    final_url = await supabase_upload(upload_ready_bytes, final_key, "video/mp4")

    try:
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
    except Exception:
        await supabase_delete(final_key)
        raise

    return {"video_url": video_url, "final_url": final_url}


@app.post("/jobs_prompt_tts")
async def create_job_with_prompt_and_tts(
    req: JobPromptTTS, _: None = Depends(require_auth)
):
    """Generate a video with synchronized speech."""
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
    user_id = req.user_context.id if req.user_context else None

    mp3_bytes = await elevenlabs_tts_bytes(req.text, req.voice_id)
    audio_key = build_storage_key(prefix, "audio", "mp3")
    audio_public_url = await supabase_upload(mp3_bytes, audio_key, "audio/mpeg")

    final_key: str | None = None
    final_url: str | None = None
    video_url: str | None = None

    try:
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
            upload_ready_bytes = prepare_video_for_upload(final_bytes)
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
            upload_ready_bytes = prepare_video_for_upload(final_bytes)
            final_key = build_storage_key(prefix, "videos", "mp4")
            final_url = await supabase_upload(
                upload_ready_bytes, final_key, "video/mp4"
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
    except Exception:
        if final_key:
            await supabase_delete(final_key)
        await supabase_delete(audio_key)
        raise

    return {
        "audio_url": audio_public_url,
        "video_url": video_url,
        "final_url": final_url,
    }


# ===== Debug =====
@app.post("/debug/head")
async def debug_head(req: HeadRequest, _: None = Depends(require_auth)):
    """Fetch metadata about a URL without downloading the entire file."""
    status, ctype, size = await head_info(req.url)
    return {"status": status, "content_type": ctype, "bytes": size}
