# Talking Pet Backend

Minimal FastAPI backend that turns a static pet photo and short script into an animated “talking pet” video by orchestrating third‑party services.

- ElevenLabs TTS → audio (MP3)
- Multiple Replicate i2v models → animation (MP4) from image + prompt
  - Hailuo-02 (default)
  - Kling v2.1
  - Wan v2.2
- Supabase Storage → persists and serves public media URLs
- Optional muxing → combines generated video + speech into final MP4

## Architecture (high level)
1. Client calls an endpoint with an image URL and prompt.
2. For TTS flow, service calls ElevenLabs to synthesize MP3.
3. Service calls Replicate with selected i2v model to generate an MP4 from the image + prompt.
4. Service uploads artifacts to Supabase Storage and returns public URLs.
5. For TTS flow, backend muxes the MP4 + MP3 using ffmpeg (via imageio‑ffmpeg), then uploads the final MP4.

OpenAPI docs available at `/docs` when running locally.

## Requirements
- Python 3.10+
- No system ffmpeg required; `imageio-ffmpeg` provides a bundled binary.

Install dependencies:

```bash
pip install -r requirements.txt
```

## Environment variables
The service expects the following environment variables (e.g., in a `.env` file):

- ELEVEN_API_KEY: ElevenLabs API key (required for `/jobs_prompt_tts`).
- REPLICATE_API_TOKEN: Replicate API token (required).
- SUPABASE_URL: Your Supabase project URL, e.g. https://<project>.supabase.co (required).
- SUPABASE_SERVICE_ROLE: Service role token used to upload to Storage (required; keep server‑side only).
- SUPABASE_BUCKET: Bucket name for uploads (default: `pets`).
- ALLOWED_ORIGIN: CORS origin, `*` by default.
- TTS_OUTPUT_FORMAT: ElevenLabs output format (default: `mp3_44100_64`).
- TTS_MAX_CHARS: Max TTS input length (default: `600`).

Tip (PowerShell):

```powershell
# Create a .env file at repo root so uvicorn auto-loads it
@'
ELEVEN_API_KEY=...
REPLICATE_API_TOKEN=...
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE=...
SUPABASE_BUCKET=pets
ALLOWED_ORIGIN=*
'@ | Out-File -Encoding UTF8 .env
```

## Run locally

```bash
uvicorn main:app --reload
```

Base URL: http://localhost:8000

## API reference

- GET /health
  - Response: { "ok": true }

- GET /models
  - Response: { 
      "supported_models": {
        "minimax/hailuo-02": {"name": "Hailuo-02", "is_default": true},
        "kling/v2.1": {"name": "Kling v2.1", "is_default": false},
        "wan/v2.2": {"name": "Wan v2.2", "is_default": false}
      },
      "default_model": "minimax/hailuo-02"
    }

- POST /jobs_prompt_only
  - Body (JSON):
    {
      "image_url": "https://example.com/pet.jpg",
      "prompt": "The dog smiles and tilts its head",
      "seconds": 6,
      "resolution": "768p",
      "model": "kling/v2.1" // optional; defaults to Hailuo-02
    }
  - Response: { "video_url": "https://.../video.mp4" }

- POST /jobs_prompt_tts
  - Body (JSON):
    {
      "image_url": "https://example.com/pet.jpg",
      "prompt": "The dog says hello",
      "text": "Hi there!",
      "voice_id": "<elevenlabs-voice-id>",
      "seconds": 6,
      "resolution": "768p",
      "model": "wan/v2.2"
    }
  - Response:
    {
      "audio_url": "https://.../audio.mp3",
      "video_url": "https://.../video.mp4",
      "final_url": "https://.../final.mp4"
    }

- POST /debug/head
  - Body: { "url": "https://example.com/file" }
  - Response: { "status": 200, "content_type": "image/jpeg", "bytes": 12345 }

Notes
- TTS requests longer than TTS_MAX_CHARS will be rejected (400).
- Generated audio larger than ~9.5 MB will be rejected (400).
- Muxing adds a small initial audio delay (~0.5s) to improve sync.

## Deployment
A ready‑to‑use Render spec is provided in `render.yaml`.

- Build: pip install -r requirements.txt
- Start: uvicorn main:app --host 0.0.0.0 --port $PORT
- Set env vars in your Render service: ELEVEN_API_KEY, REPLICATE_API_TOKEN, SUPABASE_URL, SUPABASE_SERVICE_ROLE, SUPABASE_BUCKET, ALLOWED_ORIGIN

Security
- Never expose the Supabase service role token to the browser/client.
- Restrict ALLOWED_ORIGIN in production to your actual frontend origin.

## Troubleshooting
- 401/403 from Replicate: check REPLICATE_API_TOKEN.
- 401 from ElevenLabs: check ELEVEN_API_KEY and voice_id.
- 403 from Supabase upload: ensure SUPABASE_SERVICE_ROLE is set and bucket exists.
- Video/audio out of sync: verify seconds vs audio duration; muxing uses `-shortest` and 0.5s delay.

