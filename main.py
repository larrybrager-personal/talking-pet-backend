"""
Minimal FastAPI backend (cleaned) for Talking Pet MVP
- ElevenLabs TTS → Supabase upload → SadTalker (via Replicate) → video_url
- Keeps one debug helper: /debug/head to inspect public file headers
"""

import os, time, uuid
from typing import Tuple

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ===== Environment =====
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY", "")
ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "*")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")  # e.g. https://<project>.supabase.co
SUPABASE_SERVICE_ROLE = os.getenv("SUPABASE_SERVICE_ROLE", "")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "pets")

# Replicate / SadTalker
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN", "")
SADTALKER_MODEL = os.getenv("SADTALKER_MODEL", "cjwbw/sadtalker")
SADTALKER_VERSION = os.getenv("SADTALKER_VERSION", "")  # use the specific version hash from Replicate

# TTS tuning
TTS_OUTPUT_FORMAT = os.getenv("TTS_OUTPUT_FORMAT", "mp3_44100_64")
TTS_MAX_CHARS = int(os.getenv("TTS_MAX_CHARS", "600"))

PUBLIC_BASE = f"{SUPABASE_URL}/storage/v1/object/public"
UPLOAD_BASE = f"{SUPABASE_URL}/storage/v1/object"

# ===== App =====
app = FastAPI(title="Talking Pet Backend (SadTalker)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN] if ALLOWED_ORIGIN != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== Models =====
class JobWithText(BaseModel):
    image_url: str
    text: str
    voice_id: str

class JobWithAudioURL(BaseModel):
    image_url: str
    audio_url: str

class HeadRequest(BaseModel):
    url: str

# ===== Helpers =====
async def elevenlabs_tts_bytes(text: str, voice_id: str) -> bytes:
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
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.head(url)
        if r.status_code >= 400:
            r = await c.get(url, headers={"Range": "bytes=0-1"})
        size = int(r.headers.get("content-length", "0"))
        return r.status_code, r.headers.get("content-type", ""), size

async def sadtalker_create(image_url: str, audio_url: str) -> str:
    if not (REPLICATE_API_TOKEN and SADTALKER_MODEL and SADTALKER_VERSION):
        raise HTTPException(500, "SadTalker env not set (REPLICATE_API_TOKEN, SADTALKER_MODEL, SADTALKER_VERSION)")

    a_status, a_type, a_size = await head_info(audio_url)
    i_status, i_type, i_size = await head_info(image_url)
    if a_type and "audio" not in a_type:
        raise HTTPException(400, f"audio_url content-type '{a_type}' is not audio/*")
    if i_type and "image" not in i_type:
        raise HTTPException(400, f"image_url content-type '{i_type}' is not image/*")

    headers = {
        "Authorization": f"Token {REPLICATE_API_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "version": SADTALKER_VERSION,
        "input": {
            "source_image": image_url,
            "driven_audio": audio_url,
            "preprocess": "full",
            "still_mode": True,
            "enhancer": "gfpgan",
        },
        "model": SADTALKER_MODEL,
    }
    async with httpx.AsyncClient(timeout=600) as client:
        create = await client.post("https://api.replicate.com/v1/predictions", headers=headers, json=payload)
        if create.status_code >= 400:
            raise HTTPException(create.status_code, f"Replicate create failed: {create.text}")
        pred = create.json()
        pred_id = pred.get("id")
        if not pred_id:
            raise HTTPException(500, "Replicate did not return a prediction id")
        while True:
            getr = await client.get(f"https://api.replicate.com/v1/predictions/{pred_id}", headers=headers)
            getr.raise_for_status()
            data = getr.json()
            status = data.get("status")
            if status in ("succeeded", "failed", "canceled"):
                if status != "succeeded":
                    raise HTTPException(400, f"SadTalker {status}: {data.get('error')}")
                output = data.get("output")
                if isinstance(output, list) and output:
                    return output[-1]
                elif isinstance(output, str):
                    return output
                raise HTTPException(500, "SadTalker succeeded but no output URL returned")
            time.sleep(2)

# ===== Routes =====
@app.get("/health")
async def health():
    return {"ok": True}

@app.post("/jobs_st")
async def create_job_with_audio_sadtalker(req: JobWithAudioURL):
    video_url = await sadtalker_create(req.image_url, req.audio_url)
    return {"video_url": video_url}

@app.post("/jobs_tts_st")
async def create_job_with_tts_sadtalker(req: JobWithText):
    mp3_bytes = await elevenlabs_tts_bytes(req.text, req.voice_id)
    key = f"audio/{uuid.uuid4()}.mp3"
    audio_public_url = await supabase_upload(mp3_bytes, key, "audio/mpeg")
    video_url = await sadtalker_create(req.image_url, audio_public_url)
    return {"audio_url": audio_public_url, "video_url": video_url}

# ===== Debug =====
@app.post("/debug/head")
async def debug_head(req: HeadRequest):
    status, ctype, size = await head_info(req.url)
    return {"status": status, "content_type": ctype, "bytes": size}
