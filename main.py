"""
Minimal FastAPI backend (cleaned) for Talking Pet MVP
- ElevenLabs TTS → Supabase upload → D‑ID (image + audio) → video_url
- Keeps one debug helper: /debug/head to inspect public file headers
"""

import os, base64, time, uuid
from typing import Tuple

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ===== Environment =====
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY", "")
DID_KEY = os.getenv("DID_API_KEY", "")  # if D‑ID provides key+secret, store as "key:secret"
ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "*")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")  # e.g. https://<project>.supabase.co
SUPABASE_SERVICE_ROLE = os.getenv("SUPABASE_SERVICE_ROLE", "")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "pets")

# TTS tuning (kept small for D‑ID’s 10MB limit)
TTS_OUTPUT_FORMAT = os.getenv("TTS_OUTPUT_FORMAT", "mp3_44100_64")  # e.g., mp3_44100_32 for smaller files
TTS_MAX_CHARS = int(os.getenv("TTS_MAX_CHARS", "600"))

PUBLIC_BASE = f"{SUPABASE_URL}/storage/v1/object/public"          # GET
UPLOAD_BASE = f"{SUPABASE_URL}/storage/v1/object"                  # POST (upload)

# ===== App =====
app = FastAPI(title="Talking Pet Backend (Clean)")
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
    # Public URL; add ?download=1 to force direct file body
    return f"{PUBLIC_BASE}/{SUPABASE_BUCKET}/{object_path}?download=1"

async def head_info(url: str) -> Tuple[int, str, int]:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.head(url)
        if r.status_code >= 400:
            r = await c.get(url, headers={"Range": "bytes=0-1"})
        size = int(r.headers.get("content-length", "0"))
        return r.status_code, r.headers.get("content-type", ""), size

async def did_create_talk(image_url: str, audio_url: str) -> str:
    if not DID_KEY:
        raise HTTPException(500, "DID_API_KEY not set")

    # Preflight: verify D‑ID‑friendly headers & sizes
    a_status, a_type, a_size = await head_info(audio_url)
    i_status, i_type, i_size = await head_info(image_url)
    if a_size and a_size > 9_500_000:
        raise HTTPException(400, f"Audio too large: {a_size} bytes (>9.5MB)")
    if i_size and i_size > 9_500_000:
        raise HTTPException(400, f"Image too large: {i_size} bytes (>9.5MB)")
    if a_type and "audio" not in a_type:
        raise HTTPException(400, f"audio_url content-type '{a_type}' is not audio/*")
    if i_type and "image" not in i_type:
        raise HTTPException(400, f"image_url content-type '{i_type}' is not image/*")

    auth = base64.b64encode(DID_KEY.encode()).decode()
    async with httpx.AsyncClient(timeout=600) as client:
        create = await client.post(
            "https://api.d-id.com/talks",
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
            json={
                "source_url": image_url,
                "script": {"type": "audio", "audio_url": audio_url},  # no explicit resolution; let D‑ID default
            },
        )
        if create.status_code >= 400:
            raise HTTPException(create.status_code, create.text)
        talk_id = create.json().get("id")
        if not talk_id:
            raise HTTPException(500, "No talk id returned from D‑ID")

        # Poll
        while True:
            g = await client.get(
                f"https://api.d-id.com/talks/{talk_id}",
                headers={"Authorization": f"Basic {auth}"},
            )
            g.raise_for_status()
            data = g.json()
            if data.get("status") == "done":
                return data.get("result_url")
            if data.get("status") == "error":
                raise HTTPException(400, data.get("error", "D-ID error"))
            time.sleep(2)

# ===== Routes =====
@app.get("/health")
async def health():
    return {"ok": True}

@app.post("/jobs")
async def create_job_with_audio(req: JobWithAudioURL):
    video_url = await did_create_talk(req.image_url, req.audio_url)
    return {"video_url": video_url}

@app.post("/jobs_tts")
async def create_job_with_tts(req: JobWithText):
    # 1) TTS → bytes
    mp3_bytes = await elevenlabs_tts_bytes(req.text, req.voice_id)
    # 2) Upload MP3 → public URL (forced download)
    key = f"audio/{uuid.uuid4()}.mp3"
    audio_public_url = await supabase_upload(mp3_bytes, key, "audio/mpeg")
    # 3) D‑ID create talk
    video_url = await did_create_talk(req.image_url, audio_public_url)
    return {"audio_url": audio_public_url, "video_url": video_url}

# ===== Minimal debug kept for testing =====
@app.post("/debug/head")
async def debug_head(req: HeadRequest):
    status, ctype, size = await head_info(req.url)
    return {"status": status, "content_type": ctype, "bytes": size}
