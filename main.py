"""
Talking Pet Backend - FastAPI Service

A minimal FastAPI backend that orchestrates multiple third-party services to
create "talking pet" videos from static images. The service provides two main
workflows:

1. Prompt-only: Generate animated video from image + text prompt
2. Prompt + TTS: Generate video with synchronized speech using ElevenLabs TTS

Architecture:
- ElevenLabs API → speech synthesis (MP3)
- Replicate (Hailuo-02) → video animation from image + prompt
- Supabase Storage → file storage and public URL generation
- FFmpeg → audio/video muxing for synchronized output

Endpoints:
- GET /health: Service health check
- POST /jobs_prompt_only: Create video from image + prompt
- POST /jobs_prompt_tts: Create video with synchronized speech
- POST /debug/head: Utility for inspecting remote file headers
"""

import os
import time
import uuid
import tempfile
import shutil
import subprocess
from typing import Tuple

import httpx
import imageio_ffmpeg
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ===== Environment =====
# Core service configuration
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY", "")
ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "*")

# Supabase configuration for file storage
# e.g. https://<project>.supabase.co
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE = os.getenv("SUPABASE_SERVICE_ROLE", "")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "pets")

# Replicate / Hailuo-02 configuration
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN", "")
HAILUO_MODEL = "minimax/hailuo-02"

# TTS configuration and limits
TTS_OUTPUT_FORMAT = os.getenv("TTS_OUTPUT_FORMAT", "mp3_44100_64")
TTS_MAX_CHARS = int(os.getenv("TTS_MAX_CHARS", "600"))

# Supabase Storage URL construction
PUBLIC_BASE = f"{SUPABASE_URL}/storage/v1/object/public"
UPLOAD_BASE = f"{SUPABASE_URL}/storage/v1/object"

# ===== App =====
app = FastAPI(title="Talking Pet Backend (Hailuo-02)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN] if ALLOWED_ORIGIN != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== Models =====
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


class HeadRequest(BaseModel):
    """Request body for the ``/debug/head`` endpoint."""

    url: str


# ===== Helpers =====
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

    # ElevenLabs API configuration
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
                # Supports multiple languages
                "model_id": "eleven_multilingual_v2",
                # e.g., mp3_44100_64
                "output_format": TTS_OUTPUT_FORMAT,
            },
        )
        r.raise_for_status()
        audio = r.content

        # Prevent excessively large audio files that could cause issues
        if len(audio) > 9_500_000:
            raise HTTPException(
                400,
                "Generated audio >9.5MB. Shorten script or reduce bitrate.",
            )
        return audio


async def supabase_upload(
    file_bytes: bytes, object_path: str, content_type: str
) -> str:
    """Upload a file to Supabase Storage and return a public URL.

    Args:
        file_bytes: Raw file content to upload
        object_path: Target path within the bucket (e.g., "audio/uuid.mp3")
        content_type: MIME type for the file (e.g., "audio/mpeg", "video/mp4")

    Returns:
        Public URL for accessing the uploaded file

    Raises:
        HTTPException: If Supabase credentials are missing or upload fails
    """

    # Supabase Storage upload configuration
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE:
        raise HTTPException(500, "Supabase env not set")
    upload_url = f"{UPLOAD_BASE}/{SUPABASE_BUCKET}/{object_path}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE}",
        "apikey": SUPABASE_SERVICE_ROLE,  # Supabase requires both headers
        "Content-Type": content_type,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            upload_url,
            headers=headers,
            content=file_bytes,
            params={"upsert": "true"},  # Overwrite if file exists
        )
        if r.status_code >= 400:
            raise HTTPException(
                r.status_code,
                f"Supabase upload failed: {r.text}",
            )
    # Return public URL with download parameter for proper content-type headers
    return f"{PUBLIC_BASE}/{SUPABASE_BUCKET}/{object_path}?download=1"


async def head_info(url: str) -> Tuple[int, str, int]:
    """Retrieve basic HTTP header information for a URL.

    Attempts HEAD request first, falls back to partial GET if HEAD fails.
    Useful for validating remote URLs and checking file sizes.

    Args:
        url: Remote URL to inspect

    Returns:
        Tuple of (status_code, content_type, content_length)

    Note:
        If HEAD request fails (4xx status), tries GET with Range header
        to retrieve minimal content while getting headers.
    """

    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.head(url)
        if r.status_code >= 400:
            r = await c.get(url, headers={"Range": "bytes=0-1"})
        size = int(r.headers.get("content-length", "0"))
        return r.status_code, r.headers.get("content-type", ""), size


async def replicate_video_from_prompt(
    model: str, image_url: str, prompt: str, seconds: int, resolution: str
) -> str:
    """Create a video using a specified Replicate model.

    Submits a prediction job to Replicate API and polls for completion.
    Uses synchronous polling which blocks until the video is generated.

    Args:
        model: Replicate model identifier (e.g., "minimax/hailuo-02")
        image_url: Public URL of the source image (first frame)
        prompt: Text description of desired animation
        seconds: Duration of output video
        resolution: Target resolution (e.g., "768p")

    Returns:
        Public URL of the generated video

    Raises:
        HTTPException: If API token missing, job fails, or output unavailable

    Note:
        This function blocks until video generation completes, which can
        take 30-60 seconds. In production, consider async job queues.
    """

    if not REPLICATE_API_TOKEN:
        raise HTTPException(500, "Replicate API token not set")

    headers = {
        "Authorization": f"Token {REPLICATE_API_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "input": {
            "prompt": prompt,
            "duration": seconds,
            "resolution": resolution,
            "prompt_optimizer": False,
            "first_frame_image": image_url,
        }
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


async def hailuo_video_from_prompt(
    model: str, image_url: str, prompt: str, seconds: int, resolution: str
) -> str:
    """Create a talking-pet style video using the specified Replicate model.

    Wrapper around replicate_video_from_prompt() specifically for Hailuo-02
    model. Currently just delegates to the generic Replicate function, but
    provides a place for Hailuo-specific logic if needed.

    Args:
        model: Replicate model identifier, typically "minimax/hailuo-02"
        image_url: Public URL of the pet image to animate
        prompt: Animation description (e.g., "dog smiles and wags tail")
        seconds: Video duration in seconds
        resolution: Output resolution string

    Returns:
        Public URL of the generated talking pet video
    """

    return await replicate_video_from_prompt(
        model, image_url, prompt, seconds, resolution
    )


async def mux_video_audio(video_url: str, audio_url: str) -> bytes:
    """Combine a video and an audio track into a single MP4 file.

    Downloads both files, uses FFmpeg to mux them together with timing
    adjustments for better lip-sync, then returns the combined file as bytes.

    Args:
        video_url: Public URL of the generated video (MP4)
        audio_url: Public URL of the synthesized audio (MP3)

    Returns:
        Raw bytes of the muxed MP4 file

    Process:
        1. Download video and audio to temporary files
        2. Use FFmpeg with imageio-ffmpeg to combine them
        3. Add 0.5s audio delay for better synchronization
        4. Use -shortest flag to match duration of shorter stream
        5. Clean up temporary files

    Note:
        Requires imageio-ffmpeg package which provides bundled FFmpeg binary.
        No system FFmpeg installation needed.
    """

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
        "adelay=500|500",  # add 0.5s delay to audio start
        "-shortest",
        fpath,
    ]
    subprocess.run(cmd, check=True)

    final_bytes = open(fpath, "rb").read()
    shutil.rmtree(tmpdir)
    return final_bytes


# ===== Routes =====
@app.get("/health")
async def health():
    """Simple health check used by deployment platforms."""
    return {"ok": True}


@app.post("/jobs_prompt_only")
async def create_job_with_prompt(req: JobPromptOnly):
    """Generate a video from a static image and text prompt.

    This endpoint creates an animated video by sending the image and prompt
    to Replicate's Hailuo-02 model. No audio synthesis is performed.

    Args:
        req: JobPromptOnly model containing image_url, prompt, and options

    Returns:
        JSON response with video_url field containing the generated video

    Example:
        POST /jobs_prompt_only
        {
            "image_url": "https://example.com/pet.jpg",
            "prompt": "The dog tilts its head and smiles",
            "seconds": 6,
            "resolution": "768p"
        }

        Response: {"video_url": "https://...replicate.delivery/video.mp4"}
    """
    video_url = await hailuo_video_from_prompt(
        req.model or HAILUO_MODEL,
        req.image_url,
        req.prompt,
        req.seconds,
        req.resolution,
    )
    return {"video_url": video_url}


@app.post("/jobs_prompt_tts")
async def create_job_with_prompt_and_tts(req: JobPromptTTS):
    """Generate a video with synchronized speech.

    This is the main "talking pet" endpoint that:
    1. Synthesizes speech from text using ElevenLabs TTS
    2. Generates animated video from image and prompt using Replicate
    3. Combines audio and video with FFmpeg for lip-sync
    4. Stores all artifacts in Supabase Storage

    Args:
        req: JobPromptTTS model with image, prompt, text, voice_id, and options

    Returns:
        JSON with audio_url, video_url, and final_url (muxed version)

    Process Flow:
        1. Synthesize speech using ElevenLabs
        2. Upload audio to Supabase Storage
        3. Create animated video with Hailuo
        4. Download both files and mux with FFmpeg
        5. Upload final video to Supabase Storage

    Example:
        POST /jobs_prompt_tts
        {
            "image_url": "https://example.com/dog.jpg",
            "prompt": "The dog opens its mouth and speaks happily",
            "text": "Hello! How are you today?",
            "voice_id": "21m00Tcm4TlvDq8ikWAM",
            "seconds": 6
        }
    """

    mp3_bytes = await elevenlabs_tts_bytes(req.text, req.voice_id)
    key = f"audio/{uuid.uuid4()}.mp3"
    audio_public_url = await supabase_upload(mp3_bytes, key, "audio/mpeg")
    video_url = await hailuo_video_from_prompt(
        req.model or HAILUO_MODEL,
        req.image_url,
        req.prompt,
        req.seconds,
        req.resolution,
    )

    final_bytes = await mux_video_audio(video_url, audio_public_url)
    final_key = f"videos/{uuid.uuid4()}.mp4"
    final_url = await supabase_upload(final_bytes, final_key, "video/mp4")

    return {
        "audio_url": audio_public_url,
        "video_url": video_url,
        "final_url": final_url,
    }


# ===== Debug =====
@app.post("/debug/head")
async def debug_head(req: HeadRequest):
    """Fetch metadata about a URL without downloading the entire file.

    Debug utility for inspecting remote URLs. Useful for validating
    image URLs before sending to Replicate, or checking file sizes.

    Args:
        req: HeadRequest model containing the URL to inspect

    Returns:
        JSON with status, content_type, and bytes fields

    Example:
        POST /debug/head
        {"url": "https://example.com/image.jpg"}

        Response: {
            "status": 200,
            "content_type": "image/jpeg",
            "bytes": 245760
        }
    """
    status, ctype, size = await head_info(req.url)
    return {"status": status, "content_type": ctype, "bytes": size}
