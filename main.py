"""
Minimal FastAPI backend (cleaned) for Talking Pet MVP
- ElevenLabs TTS → Supabase upload → Hailuo-02 (via Replicate) → video_url
- Keeps one debug helper: /debug/head to inspect public file headers
"""

import os, time, uuid, tempfile, shutil, subprocess
from typing import Tuple

import httpx
import imageio_ffmpeg
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ===== Environment =====
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY", "")
ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "*")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")  # e.g. https://<project>.supabase.co
SUPABASE_SERVICE_ROLE = os.getenv("SUPABASE_SERVICE_ROLE", "")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "pets")

# Replicate / Hailuo-02
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN", "")
HAILUO_MODEL = "minimax/hailuo-02"

# TTS tuning
TTS_OUTPUT_FORMAT = os.getenv("TTS_OUTPUT_FORMAT", "mp3_44100_64")
TTS_MAX_CHARS = int(os.getenv("TTS_MAX_CHARS", "600"))

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
    """

    image_url: str
    prompt: str
    seconds: int = 6
    resolution: str = "768p"


class JobPromptTTS(BaseModel):
    """Request body for generating a video and matching audio.

    Extends :class:`JobPromptOnly` with script text and desired ElevenLabs
    voice identifier so the backend can synthesize speech and mux it with the
    generated video.
    """

    image_url: str
    prompt: str
    text: str
    voice_id: str
    seconds: int = 6
    resolution: str = "768p"


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
        raise HTTPException(400, f"Text too long for demo (max {TTS_MAX_CHARS} chars). Please shorten your script.")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            url,
            headers={"xi-api-key": ELEVEN_API_KEY, "Content-Type": "application/json"},
            json={
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "output_format": TTS_OUTPUT_FORMAT,
            },
        )
        r.raise_for_status()
        audio = r.content
        if len(audio) > 9_500_000:
            raise HTTPException(400, "Generated audio is too large (>9.5MB). Shorten the script or reduce bitrate.")
        return audio

async def supabase_upload(file_bytes: bytes, object_path: str, content_type: str) -> str:
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
        r = await client.post(upload_url, headers=headers, content=file_bytes, params={"upsert": "true"})
        if r.status_code >= 400:
            raise HTTPException(r.status_code, f"Supabase upload failed: {r.text}")
    return f"{PUBLIC_BASE}/{SUPABASE_BUCKET}/{object_path}?download=1"

async def head_info(url: str) -> Tuple[int, str, int]:
    """Retrieve basic HTTP header information for a URL."""

    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.head(url)
        if r.status_code >= 400:
            r = await c.get(url, headers={"Range": "bytes=0-1"})
        size = int(r.headers.get("content-length", "0"))
        return r.status_code, r.headers.get("content-type", ""), size

async def replicate_video_from_prompt(
    model: str, image_url: str, prompt: str, seconds: int, resolution: str
) -> str:
    """Create a video using a specified Replicate model."""

    if not REPLICATE_API_TOKEN:
        raise HTTPException(500, "Replicate API token not set")

    headers = {"Authorization": f"Token {REPLICATE_API_TOKEN}", "Content-Type": "application/json"}
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
            raise HTTPException(create.status_code, f"Replicate {model} create failed: {create.text}")
        pred = create.json()
        pred_id = pred.get("id")
        if not pred_id:
            raise HTTPException(500, "Replicate did not return a prediction id")

        while True:
            getr = await client.get(
                f"https://api.replicate.com/v1/predictions/{pred_id}", headers=headers
            )
            getr.raise_for_status()
            data = getr.json()
            status = data.get("status")
            if status in ("succeeded", "failed", "canceled"):
                if status != "succeeded":
                    raise HTTPException(
                        400,
                        f"{model} {status}: {data.get('error')} | logs: {data.get('logs')}",
                    )
                output = data.get("output")
                if isinstance(output, list) and output:
                    return output[-1]
                if isinstance(output, str):
                    return output
                raise HTTPException(500, "Replicate succeeded but no output URL")
            time.sleep(2)

async def hailuo_video_from_prompt(
    image_url: str, prompt: str, seconds: int, resolution: str
) -> str:
    """Create a talking-pet style video using the Hailuo-02 model on Replicate."""

    return await replicate_video_from_prompt(
        HAILUO_MODEL, image_url, prompt, seconds, resolution
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
        with open(vpath, "wb") as f: f.write(vr.content)
        ar = await client.get(audio_url)
        ar.raise_for_status()
        with open(apath, "wb") as f: f.write(ar.content)

    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg_path,
        "-y",
        "-i", vpath,
        "-i", apath,
        "-c:v", "copy",
        "-c:a", "aac",
        "-af", "adelay=500|500",  # add 0.5s delay to audio start
        "-shortest",
        fpath
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
    """Generate a video from a static image and text prompt."""
    video_url = await hailuo_video_from_prompt(req.image_url, req.prompt, req.seconds, req.resolution)
    return {"video_url": video_url}

@app.post("/jobs_prompt_tts")
async def create_job_with_prompt_and_tts(req: JobPromptTTS):
    """Generate a video with synchronized speech.

    Steps:
        1. Synthesize speech using ElevenLabs.
        2. Create an animated video with Hailuo.
        3. Mux the audio and video together and store the final file in Supabase.
    """

    mp3_bytes = await elevenlabs_tts_bytes(req.text, req.voice_id)
    key = f"audio/{uuid.uuid4()}.mp3"
    audio_public_url = await supabase_upload(mp3_bytes, key, "audio/mpeg")
    video_url = await hailuo_video_from_prompt(req.image_url, req.prompt, req.seconds, req.resolution)

    final_bytes = await mux_video_audio(video_url, audio_public_url)
    final_key = f"videos/{uuid.uuid4()}.mp4"
    final_url = await supabase_upload(final_bytes, final_key, "video/mp4")

    return {"audio_url": audio_public_url, "video_url": video_url, "final_url": final_url}

# ===== Debug =====
@app.post("/debug/head")
async def debug_head(req: HeadRequest):
    """Fetch metadata about a URL without downloading the entire file."""
    status, ctype, size = await head_info(req.url)
    return {"status": status, "content_type": ctype, "bytes": size}
