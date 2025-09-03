import os, base64, time, uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

# ==== ENV ====
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY", "")
DID_KEY = os.getenv("DID_API_KEY", "")            # format: "key:secret"
ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "*")
# Supabase (bucket should be PUBLIC during MVP)
SUPABASE_URL = os.getenv("SUPABASE_URL", "")       # e.g. https://xxxx.supabase.co
SUPABASE_SERVICE_ROLE = os.getenv("SUPABASE_SERVICE_ROLE", "")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "pets")

PUBLIC_BASE = f"{SUPABASE_URL}/storage/v1/object/public"          # GET
UPLOAD_BASE = f"{SUPABASE_URL}/storage/v1/object"                  # POST (upload)

# ==== APP ====
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN] if ALLOWED_ORIGIN != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==== MODELS ====
class TTSRequest(BaseModel):
    text: str
    voice_id: str = "21m00Tcm4TlvDq8ikWAM"  # sample stock voice

class JobWithAudioURL(BaseModel):
    image_url: str   # public https URL of the pet image
    audio_url: str   # public https URL of MP3 from TTS

class JobWithText(BaseModel):
    image_url: str   # public https URL of the pet image
    text: str
    voice_id: str = "21m00Tcm4TlvDq8ikWAM"

# ==== HELPERS ====
async def elevenlabs_tts_bytes(text: str, voice_id: str) -> bytes:
    if not ELEVEN_API_KEY:
        raise HTTPException(500, "ELEVEN_API_KEY not set")
    # Keep audio small for D-ID (10MB max). Use lower bitrate and cap text length.
    OUTPUT_FORMAT = os.getenv("TTS_OUTPUT_FORMAT", "mp3_44100_64")  # smaller than 128kbps
    MAX_CHARS = int(os.getenv("TTS_MAX_CHARS", "600"))  # ~30–45s typical
    if len(text) > MAX_CHARS:
        raise HTTPException(400, f"Text too long for demo (max {MAX_CHARS} chars). Please shorten your script.")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            url,
            headers={"xi-api-key": ELEVEN_API_KEY, "Content-Type": "application/json"},
            json={
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "output_format": OUTPUT_FORMAT,
            },
        )
        r.raise_for_status()
        audio = r.content  # MP3 bytes
        # Guardrail: fail fast if file would exceed D-ID's 10MB limit
        if len(audio) > 9_500_000:
            raise HTTPException(400, "Generated audio is too large (>9.5MB). Please shorten the script or reduce bitrate.")
        return audio  # MP3 bytes

async def supabase_upload(file_bytes: bytes, object_path: str, content_type: str) -> str:
    """Uploads bytes to Supabase Storage using service role; returns PUBLIC URL."""
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
    # Public URL (bucket must be public for this to be fetchable without a token)
    return f"{PUBLIC_BASE}/{SUPABASE_BUCKET}/{object_path}"

async def did_create_talk(image_url: str, audio_url: str) -> str:
    if not DID_KEY:
        raise HTTPException(500, "DID_API_KEY not set")
    auth = base64.b64encode(DID_KEY.encode()).decode()
    async with httpx.AsyncClient(timeout=600) as client:
        create = await client.post(
            "https://api.d-id.com/talks",
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
            json={
                "source_url": image_url,
                "script": {"type": "audio", "audio_url": audio_url},
                "config": {"resolution": "720p"}
            },
        )
        if create.status_code >= 400:
            raise HTTPException(create.status_code, create.text)
        talk_id = create.json().get("id")
        if not talk_id:
            raise HTTPException(500, "No talk id returned")
        # poll
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
                raise HTTPException(500, data.get("error", "D-ID error"))
            time.sleep(2)

# ==== ROUTES & DEBUG ====
@app.get("/health")
async def health():
    return {"ok": True}

@app.get("/debug/env")
async def debug_env():
    return {
        "ELEVEN_API_KEY": bool(ELEVEN_API_KEY),
        "DID_API_KEY": bool(DID_KEY),
        "SUPABASE_URL": bool(SUPABASE_URL),
        "SUPABASE_SERVICE_ROLE": bool(SUPABASE_SERVICE_ROLE),
        "SUPABASE_BUCKET": SUPABASE_BUCKET,
    }

@app.get("/debug/voices")
async def debug_voices():
    if not ELEVEN_API_KEY:
        raise HTTPException(500, "ELEVEN_API_KEY not set")
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(
            "https://api.elevenlabs.io/v1/voices",
            headers={"xi-api-key": ELEVEN_API_KEY},
        )
        r.raise_for_status()
        # return only minimal info
        data = r.json()
        voices = [{"name": v.get("name"), "voice_id": v.get("voice_id")} for v in data.get("voices", [])]
        return {"voices": voices}

@app.post("/jobs")
async def create_job_with_audio(req: JobWithAudioURL):
    """Use pre-generated audio (audio_url) + image_url to create a D-ID video."""
    video_url = await did_create_talk(req.image_url, req.audio_url)
    return {"video_url": video_url}

@app.post("/jobs_tts")
async def create_job_with_tts(req: JobWithText):
    """End-to-end: TTS via ElevenLabs → upload MP3 to Supabase → D-ID → return MP4 URL."""
    try:
        # 1) TTS → bytes
        mp3_bytes = await elevenlabs_tts_bytes(req.text, req.voice_id)
        # 2) Upload MP3 to Supabase
        key = f"audio/{uuid.uuid4()}.mp3"
        audio_public_url = await supabase_upload(mp3_bytes, key, "audio/mpeg")
        # 3) Call D-ID with image + audio URLs
        video_url = await did_create_talk(req.image_url, audio_public_url)
        return {"audio_url": audio_public_url, "video_url": video_url}
    except httpx.HTTPStatusError as e:
        # bubble up provider error details for easier debugging
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
