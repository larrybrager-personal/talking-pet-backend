"""
Minimal FastAPI backend (cleaned) for Talking Pet MVP
- ElevenLabs TTS → Supabase upload → Hailuo-02 (via Replicate) → video_url
- Keeps one debug helper: /debug/head to inspect public file headers
"""

import os
import secrets
import time
import uuid
import tempfile
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Tuple

import httpx
import imageio_ffmpeg
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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

# Supported i2v models configuration
SUPPORTED_MODELS = {
    "minimax/hailuo-02": {
        "name": "Hailuo-02",
        "default_params": {
            "prompt_optimizer": False,
        },
        "param_mapping": {
            "image_url": "first_frame_image",
            "prompt": "prompt",
            "seconds": "duration",
            "resolution": "resolution",
        },
        "supported_resolutions": ["512p", "768p", "1080p"],
    },
    "wan-video/wan-2.1": {
        "name": "Wan v2.1",
        "default_params": {
            "format": "wan2.1",
        },
        "param_mapping": {
            "image_url": "image",
            "prompt": "prompt",
            "seconds": "duration",
            "resolution": "resolution",
        },
        "supported_resolutions": ["768p", "1080p"],
    },
    "kwaivgi/kling-v2.1": {
        "name": "Kling v2.1",
        "default_params": {
            "mode": "standard",
            "aspect_ratio": "1:1",
        },
        "param_mapping": {
            "image_url": "start_image",
            "prompt": "prompt",
            "seconds": "duration",
            "resolution": "aspect_ratio",  # Kling uses aspect ratio
        },
        "supported_resolutions": ["720p", "1080p"],
    },
    "wan-video/wan-2.2-s2v": {
        "name": "Wan v2.2",
        "default_params": {
            "guidance_scale": 7.5,
            "num_inference_steps": 25,
        },
        "param_mapping": {
            "image_url": "image",
            "prompt": "prompt",
            "seconds": "duration",
            "resolution": "resolution",
            "audio_url": "audio",  # Speech-to-video model requires audio
        },
    },
    "bytedance/seedance-1-lite": {
        "name": "SeeDance-1 Lite",
        "default_params": {
            "guidance_scale": 7.5,
            "num_inference_steps": 20,
        },
        "param_mapping": {
            "image_url": "image",
            "prompt": "prompt",
            "seconds": "duration",
            "resolution": "resolution",
        },
        "supported_resolutions": ["480p", "720p", "1080p"],
    },
}

# Default model
DEFAULT_MODEL = "wan-video/wan-2.1"

# TTS tuning
TTS_OUTPUT_FORMAT = os.getenv("TTS_OUTPUT_FORMAT", "mp3_44100_64")
TTS_MAX_CHARS = int(os.getenv("TTS_MAX_CHARS", "600"))

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


class JobPromptOnly(BaseModel):
    """Request body for generating a video directly from a prompt.

    Attributes:
        image_url: Publicly accessible image that provides the first frame.
        prompt: Text prompt describing the desired animation.
        seconds: Duration of the generated video.
        resolution: Target output resolution, defaults to 768p.
        model: Optional Replicate model identifier. Defaults to Hailuo-02.
    """

    image_url: str
    prompt: str
    seconds: int = 6
    resolution: str = "768p"
    model: str | None = None
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
        model: Optional Replicate model identifier. Defaults to Hailuo-02.
    """

    image_url: str
    prompt: str
    text: str
    voice_id: str
    seconds: int = 6
    resolution: str = "768p"
    model: str | None = None
    user_context: UserContext | None = None


class HeadRequest(BaseModel):
    """Request body for the ``/debug/head`` endpoint."""

    url: str


# ===== Helpers =====
def get_model_config(model: str) -> dict:
    """Get configuration for a supported model.

    Args:
        model: Model identifier (e.g., 'minimax/hailuo-02')

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
) -> dict:
    """Build the payload for a specific model based on its parameter mapping.

    Args:
        model: Model identifier
        image_url: Input image URL
        prompt: Text prompt
        seconds: Duration in seconds
        resolution: Target resolution or aspect ratio
        audio_url: Audio URL for speech-to-video models (optional)

    Returns:
        Payload dictionary for the model
    """
    config = get_model_config(model)
    param_mapping = config["param_mapping"]
    default_params = config.get("default_params", {})

    # Build payload using parameter mapping
    payload = {"input": default_params.copy()}

    # Map standard parameters to model-specific names
    if "image_url" in param_mapping:
        payload["input"][param_mapping["image_url"]] = image_url
    if "prompt" in param_mapping:
        payload["input"][param_mapping["prompt"]] = prompt
    if "seconds" in param_mapping:
        # Handle special case for Kling which only accepts duration 5 or 10
        if model == "kwaivgi/kling-v2.1":
            # Map seconds to valid Kling duration values
            if seconds <= 5:
                payload["input"][param_mapping["seconds"]] = 5
            else:
                payload["input"][param_mapping["seconds"]] = 10
        else:
            payload["input"][param_mapping["seconds"]] = seconds
    if "resolution" in param_mapping:
        # Handle special case for Kling which uses aspect ratio
        if model == "kwaivgi/kling-v2.1":
            # Convert resolution to aspect ratio for Kling
            payload["input"].setdefault("mode", "standard")
            if resolution == "1080p":
                payload["input"]["mode"] = "pro"
                payload["input"][param_mapping["resolution"]] = "16:9"
            elif resolution == "1024p":
                payload["input"]["mode"] = "standard"
                payload["input"][param_mapping["resolution"]] = "16:9"
            else:
                payload["input"]["mode"] = "standard"
                payload["input"][param_mapping["resolution"]] = "1:1"
        elif model == "bytedance/seedance-1-lite":
            # SeeDance only accepts "480p", "720p", "1080p"
            if resolution == "480p":
                payload["input"][param_mapping["resolution"]] = "480p"
            elif resolution == "720p":
                payload["input"][param_mapping["resolution"]] = "720p"
            elif resolution == "1080p":
                payload["input"][param_mapping["resolution"]] = "1080p"
            elif resolution == "1024p":
                payload["input"][param_mapping["resolution"]] = "1080p"
            elif resolution == "768p":
                payload["input"][param_mapping["resolution"]] = "720p"
            else:
                # Default to 720p for any other resolution
                payload["input"][param_mapping["resolution"]] = "720p"
        else:
            payload["input"][param_mapping["resolution"]] = resolution
    if "audio_url" in param_mapping and audio_url:
        payload["input"][param_mapping["audio_url"]] = audio_url

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
    created_at: datetime | None = None,
) -> None:
    """Persist a generated pet video record via Supabase PostgREST.

    Supabase's current schema omits the previous ``storage_key`` column, so we
    only persist the public ``video_url`` alongside the other metadata fields.
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
) -> str:
    """Create a video using a specified Replicate model."""

    if not REPLICATE_API_TOKEN:
        raise HTTPException(500, "Replicate API token not set")

    # Validate model and build payload
    payload = build_model_payload(
        model, image_url, prompt, seconds, resolution, audio_url
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
            time.sleep(2)


async def generate_video_from_prompt(
    model: str,
    image_url: str,
    prompt: str,
    seconds: int,
    resolution: str,
    audio_url: str = None,
) -> str:
    """Create a talking-pet style video using the specified Replicate model."""

    return await replicate_video_from_prompt(
        model, image_url, prompt, seconds, resolution, audio_url
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


# ===== Routes =====
@app.get("/health")
async def health(_: None = Depends(require_auth)):
    """Simple health check used by deployment platforms."""
    return {"ok": True}


@app.get("/models")
async def list_supported_models(_: None = Depends(require_auth)):
    """List all supported i2v models and their configurations."""
    models = {}
    for model_id, config in SUPPORTED_MODELS.items():
        models[model_id] = {
            "name": config["name"],
            "is_default": model_id == DEFAULT_MODEL,
        }
        if "supported_resolutions" in config:
            models[model_id]["supported_resolutions"] = config["supported_resolutions"]
    return {"supported_models": models, "default_model": DEFAULT_MODEL}


@app.post("/jobs_prompt_only")
async def create_job_with_prompt(
    req: JobPromptOnly, _: None = Depends(require_auth)
):
    """Generate a video from a static image and text prompt."""
    model = req.model or DEFAULT_MODEL
    prefix = resolve_user_storage_prefix(req.user_context)
    user_id = req.user_context.id if req.user_context else None

    # Validate that speech-to-video models are not used for prompt-only requests
    if model == "wan-video/wan-2.2-s2v":
        raise HTTPException(
            400,
            "wan-video/wan-2.2-s2v is a speech-to-video model that requires audio. "
            "Use /jobs_prompt_tts endpoint instead.",
        )

    video_url = await generate_video_from_prompt(
        model,
        req.image_url,
        req.prompt,
        req.seconds,
        req.resolution,
    )
    video_bytes = await fetch_binary(video_url)
    final_key = build_storage_key(prefix, "videos", "mp4")
    final_url = await supabase_upload(video_bytes, final_key, "video/mp4")

    try:
        await insert_pet_video(
            user_id=user_id,
            video_url=final_url,
            image_url=req.image_url,
            script=None,
            prompt=req.prompt,
            voice_id=None,
            resolution=req.resolution,
            duration=req.seconds,
        )
    except Exception:
        await supabase_delete(final_key)
        raise

    return {"video_url": video_url, "final_url": final_url}


@app.post("/jobs_prompt_tts")
async def create_job_with_prompt_and_tts(
    req: JobPromptTTS, _: None = Depends(require_auth)
):
    """Generate a video with synchronized speech.

    Steps:
        1. Synthesize speech using ElevenLabs.
        2. Create an animated video with the selected model.
        3. For speech-to-video models (like Wan), provide the audio to the model.
        4. For other models, mux the audio and video together and store the final file.
    """
    model = req.model or DEFAULT_MODEL
    prefix = resolve_user_storage_prefix(req.user_context)
    user_id = req.user_context.id if req.user_context else None

    mp3_bytes = await elevenlabs_tts_bytes(req.text, req.voice_id)
    audio_key = build_storage_key(prefix, "audio", "mp3")
    audio_public_url = await supabase_upload(mp3_bytes, audio_key, "audio/mpeg")

    final_key: str | None = None
    final_url: str | None = None
    video_url: str | None = None

    try:
        # For speech-to-video models like Wan, pass the audio URL to the model
        if model == "wan-video/wan-2.2-s2v":
            video_url = await generate_video_from_prompt(
                model,
                req.image_url,
                req.prompt,
                req.seconds,
                req.resolution,
                audio_public_url,
            )
            # For speech-to-video models, the video already has synced audio
            final_key = build_storage_key(prefix, "videos", "mp4")
            final_bytes = await fetch_binary(video_url)
            final_url = await supabase_upload(final_bytes, final_key, "video/mp4")
        else:
            # For other models, generate video separately and mux with audio
            video_url = await generate_video_from_prompt(
                model,
                req.image_url,
                req.prompt,
                req.seconds,
                req.resolution,
            )

            final_bytes = await mux_video_audio(video_url, audio_public_url)
            final_key = build_storage_key(prefix, "videos", "mp4")
            final_url = await supabase_upload(final_bytes, final_key, "video/mp4")

        await insert_pet_video(
            user_id=user_id,
            video_url=final_url,
            image_url=req.image_url,
            script=req.text,
            prompt=req.prompt,
            voice_id=req.voice_id,
            resolution=req.resolution,
            duration=req.seconds,
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
