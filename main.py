import os, base64, time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

# ENV
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY", "")
DID_KEY = os.getenv("DID_API_KEY", "")  # format: "key:secret" (D-ID Basic auth pair)
ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "*")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN] if ALLOWED_ORIGIN != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TTSRequest(BaseModel):
    text: str
    voice_id: str = "21m00Tcm4TlvDq8ikWAM"  # sample stock voice

class JobRequest(BaseModel):
    image_url: str   # public https URL of the pet image
    audio_url: str   # public https URL of MP3 from TTS

@app.get("/health")
async def health():
    return {"ok": True}

@app.post("/tts")
async def tts(req: TTSRequest):
    """Generate MP3 bytes from ElevenLabs. (For quick testing; for prod, upload to storage and return a URL.)"""
    if not ELEVEN_API_KEY:
        raise HTTPException(500, "ELEVEN_API_KEY not set")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{req.voice_id}"
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            url,
            headers={"xi-api-key": ELEVEN_API_KEY, "Content-Type": "application/json"},
            json={"text": req.text, "model_id": "eleven_multilingual_v2", "output_format": "mp3_44100_128"},
        )
        r.raise_for_status()
        return {
            "ok": True,
            "note": "This endpoint returns bytes in a real app; for MVP keep TTS client-side or upload to storage."
        }

@app.post("/jobs")
async def create_job(req: JobRequest):
    """Call D-ID Talks with image+audio; returns MP4 URL when done."""
    if not DID_KEY:
        raise HTTPException(500, "DID_API_KEY not set")
    auth = base64.b64encode(DID_KEY.encode()).decode()
    async with httpx.AsyncClient(timeout=600) as client:
        # create talk
        create = await client.post(
            "https://api.d-id.com/talks",
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
            json={"source_url": req.image_url, "audio_url": req.audio_url, "config": {"resolution": "720p"}}
        )
        if create.status_code >= 400:
            raise HTTPException(create.status_code, create.text)
        talk_id = create.json().get("id")
        if not talk_id:
            raise HTTPException(500, "No talk id returned")

        # poll
        while True:
            g = await client.get(f"https://api.d-id.com/talks/{talk_id}",
                                 headers={"Authorization": f"Basic {auth}"})
            g.raise_for_status()
            data = g.json()
            status = data.get("status")
            if status == "done":
                return {"video_url": data.get("result_url")}
            if status == "error":
                raise HTTPException(500, data.get("error", "D-ID error"))
            time.sleep(2)
