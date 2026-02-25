# Talking Pet Backend

FastAPI backend that turns a static pet image and short prompt/script into a talking pet video.

## What this service does
- Generates speech with ElevenLabs (`/jobs_prompt_tts` flow).
- Chooses and runs an image-to-video model on Replicate.
- Optionally muxes generated audio + video for non-native-audio models.
- Uploads outputs to Supabase Storage and returns public URLs.

This repo is designed so both humans and AI agents can quickly understand and drive the API without digging through implementation details first.

---

## End-to-end flow

### Flow A: Prompt-only video (`POST /jobs_prompt_only`)
1. Validate request body and resolve target model/settings.
2. Normalize duration/resolution/fps to values that model supports.
3. Submit generation to Replicate.
4. Upload resulting MP4 to Supabase.
5. Return `video_url`.

### Flow B: Prompt + TTS (`POST /jobs_prompt_tts`)
1. Validate request body and enforce `TTS_MAX_CHARS`.
2. Generate MP3 from ElevenLabs.
3. Upload MP3 to Supabase (`audio_url`).
4. Resolve model/settings and generate video on Replicate.
5. Upload generated MP4 (`video_url`).
6. If model output already contains synced audio (Wan S2V / Kling family), return `final_url = video_url`.
7. Otherwise mux video + audio with ffmpeg, upload muxed MP4, and return `final_url`.

### Optional helper: model intent routing (`POST /resolve_model`)
Use this endpoint before job creation to let backend choose the best model for quality/plan intent and normalize settings.

---

## Current model catalog (high level)

The backend exposes a richer per-model metadata object via `GET /models`.

Routing defaults:
- `fast`: `wan-video/wan2.6-i2v-flash` (default)
- `premium`: `kwaivgi/kling-v2.6`
- `budget`: `bytedance/seedance-1-pro-fast`
- `legacyFallback`: `wan-video/wan-2.2-s2v`

Supported slugs currently include:
- `wan-video/wan2.6-i2v-flash`
- `wan-video/wan-2.6-i2v`
- `minimax/hailuo-2.3`
- `minimax/hailuo-2.3-fast`
- `kwaivgi/kling-v2.6`
- `kwaivgi/kling-v2.5-turbo-pro`
- `bytedance/seedance-1-pro-fast`
- `bytedance/seedance-1-pro`
- `wan-video/wan-2.2-s2v` (legacy/manual override)

Legacy slugs are normalized server-side (for backward compatibility) before validation/submission.

---

## Requirements
- Python 3.10+
- `pip install -r requirements.txt`

```bash
pip install -r requirements.txt
```

---

## Environment variables

Required for full production flow:
- `REPLICATE_API_TOKEN`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE`

Required for TTS endpoints:
- `ELEVEN_API_KEY`

Optional:
- `SUPABASE_BUCKET` (default `pets`)
- `ALLOWED_ORIGIN` (default `*`)
- `TTS_OUTPUT_FORMAT` (default `mp3_44100_64`)
- `TTS_MAX_CHARS` (default `600`)
- `API_AUTH_ENABLED` (`true`/`false`, default `false`)
- `API_AUTH_TOKEN` (required only when auth enabled)

---

## Local run

```bash
uvicorn main:app --reload
```

Local base URL: `http://localhost:8000`

OpenAPI docs: `http://localhost:8000/docs`

---

## API quick reference

### `GET /health`
Response:
```json
{"ok": true}
```

### `GET /models`
Returns:
- `supported_models` with UI metadata (`tier`, `quality_label`, capabilities, tunables, supported durations/fps/resolutions)
- `default_model`
- `routing_defaults`

### `POST /resolve_model`
Request (example):
```json
{
  "seconds": 6,
  "resolution": "768p",
  "quality": "balanced",
  "fps": 30,
  "has_audio": false,
  "model_override": null,
  "model_params": {"fps": 30},
  "user_context": {
    "id": "uuid",
    "plan_tier": "creator"
  }
}
```

Response includes:
- `resolved_model_slug`
- `resolved` (normalized `seconds`/`resolution`/`fps`/`quality`)
- `resolved_defaults`
- `resolved_meta`
- `plan_tier`

### `POST /jobs_prompt_only`
Request (example):
```json
{
  "image_url": "https://example.com/pet.jpg",
  "prompt": "A friendly dog smiles and blinks.",
  "seconds": 6,
  "resolution": "768p",
  "quality": "fast",
  "fps": 24,
  "model": null,
  "model_override": null,
  "model_params": {"fps": 24},
  "user_context": {"id": "uuid", "plan_tier": "free"}
}
```

Response:
```json
{"video_url": "https://.../video.mp4"}
```

### `POST /jobs_prompt_tts`
Request (example):
```json
{
  "image_url": "https://example.com/pet.jpg",
  "prompt": "A calm cat speaks naturally.",
  "text": "Hello there, how are you?",
  "voice_id": "eleven-voice-id",
  "seconds": 6,
  "resolution": "768p",
  "quality": "quality",
  "model": null,
  "model_override": null,
  "model_params": {"mode": "pro"},
  "user_context": {"id": "uuid", "plan_tier": "studio"}
}
```

Response:
```json
{
  "audio_url": "https://.../audio.mp3",
  "video_url": "https://.../video.mp4",
  "final_url": "https://.../final.mp4"
}
```

### `POST /debug/head`
Request:
```json
{"url": "https://example.com/file"}
```

Response:
```json
{"status": 200, "content_type": "image/jpeg", "bytes": 12345}
```

---

## Authentication behavior

When `API_AUTH_ENABLED=true`, all endpoints require:

```http
Authorization: Bearer <API_AUTH_TOKEN>
```

When `API_AUTH_ENABLED=false` (default), auth is bypassed.

---

## Validation and normalization notes
- Unsupported model slugs are rejected unless normalized from known legacy aliases.
- Quality-driven routing uses plan tier + intent (`fast`, `balanced`, `cheap`, `quality`).
- Durations are snapped to nearest supported lower value where required (for model enums).
- Resolution aliases are normalized (`768p`→`720p`, `1024p`→`1080p`) when needed.
- `model_params` are filtered against model-specific allowlists.
- `/jobs_prompt_only` rejects legacy `wan-video/wan-2.2-s2v` because it requires audio.

---

## Deployment
A Render spec is provided in `render.yaml`.

- Build: `pip install -r requirements.txt`
- Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`

Security reminders:
- Never expose `SUPABASE_SERVICE_ROLE` in clients.
- Restrict `ALLOWED_ORIGIN` in production.
- Keep `API_AUTH_TOKEN` server-side only.

---

## Local validation commands

```bash
flake8 main.py
black --check main.py
python -m py_compile main.py
pytest -q
```

---

## Repository docs map
- `README.md`: architecture + API + env + runbook (this file)
- `MODEL_ROUTING_FRONTEND_GUIDE.md`: frontend-oriented routing and payload guidance
- `KNOWN_GAPS.md`: backlog of gaps/follow-ups
- `PROGRESS_LOG.md`: timestamped change history
