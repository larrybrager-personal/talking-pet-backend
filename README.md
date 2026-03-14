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
5. Return both:
   - `video_url`: provider-generated URL returned by Replicate.
   - `final_url`: Supabase URL for the backend-managed MP4 artifact (this is what clients should persist/play).

### Flow B: Prompt + TTS (`POST /jobs_prompt_tts`)
1. Validate request body and enforce `TTS_MAX_CHARS`.
2. Generate MP3 from ElevenLabs.
3. Upload MP3 to Supabase (`audio_url`).
4. Resolve model/settings and generate video on Replicate.
5. Capture model output URL as `video_url` (provider-generated).
6. If selected model `supportsAudioIn`, pass uploaded TTS audio into generation and re-upload returned MP4 to Supabase as `final_url` (no mux step).
7. Otherwise mux model video + TTS audio with ffmpeg, upload muxed MP4 to Supabase, and return muxed `final_url`.

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
- `IDEMPOTENCY_POLL_INTERVAL_SEC` (default `1`)
- `IDEMPOTENCY_MAX_WAIT_SEC` (default `900`)
- `REPLICATE_POLL_INTERVAL_SEC` (default `2`)
- `REPLICATE_POLL_TIMEOUT_SEC` (default `900`)
- `FETCH_MAX_BYTES` (default `52428800`, 50MB max download for remote binary fetches)
- `DEBUG_FETCH_MAX_BYTES` (default `15728640`, 15MB max download for `/debug/final_video`)
- `ALLOW_PRIVATE_URL_FETCHES` (default `false`; when `false`, outbound fetches reject non-public/private hosts)

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

Capability semantics used by `supported_models[*].capabilities`:
- `supportsAudioIn`: model accepts externally supplied audio conditioning input.
- `generatesAudio`: model may generate an internal audio track on its own.

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
Request (snake_case example):
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
  "user_context": {"id": "uuid", "plan_tier": "free"},
  "request_id": "c8852fb3-6bfd-47f8-9634-dd9f53c208f2"
}
```

Response:
```json
{
  "video_url": "https://provider.example/video.mp4",
  "final_url": "https://supabase.example/storage/v1/object/public/.../final.mp4"
}
```

### `POST /jobs_prompt_tts`
Request (snake_case example):
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
  "user_context": {"id": "uuid", "plan_tier": "studio"},
  "request_id": "4eb3eb42-6b9f-4454-b64a-cb6b053f2895"
}
```

Response:
```json
{
  "audio_url": "https://.../audio.mp3",
  "video_url": "https://provider.example/video.mp4",
  "final_url": "https://.../final.mp4"
}
```


Accepted request field aliases on job endpoints (snake_case and camelCase are both accepted):

| Canonical field | Also accepted aliases |
|---|---|
| `image_url` | `imageUrl` |
| `voice_id` (`/jobs_prompt_tts`) | `voiceId` |
| `model_override` | `modelOverride`, `selectedOverrideModel` |
| `model_params` | `modelParams` |
| `user_context` | `userContext` |
| `user_context.plan_tier` | `userContext.planTier` |
| `request_id` | `requestId` |


`final_url` behavior (canonical playback contract):
- `/jobs_prompt_only`: always a backend-uploaded Supabase artifact; this is the playback URL frontend clients should persist/use.
- `/jobs_prompt_tts` + `supportsAudioIn=true`: backend re-uploads the generated MP4 as `final_url` (no mux).
- `/jobs_prompt_tts` + `supportsAudioIn=false`: backend creates a new muxed MP4 artifact and returns that as `final_url`.

Persistence semantics (`pet_videos`):
- `final_url`: canonical playback URL (matches API `final_url`).
- `provider_video_url`: raw provider output URL when applicable.
- `video_url`: backward-compatible mirror of `final_url`.

### Response-shape table (frontend typing)

| Endpoint | Response shape |
|---|---|
| `GET /health` | `{ ok: boolean }` |
| `GET /models` | `{ supported_models: Record<string, ModelMeta>, default_model: string, routing_defaults: RoutingDefaults }` |
| `POST /resolve_model` | `{ model: string, resolved_model_slug: string, plan_tier: string, meta: object, resolved: { seconds: number, resolution: string, fps: number \| null, quality: string } }` |
| `POST /jobs_prompt_only` | `{ video_url: string, final_url: string }` |
| `POST /jobs_prompt_tts` | `{ audio_url: string, video_url: string, final_url: string }` |
| `POST /debug/head` | `{ status: number, content_type: string \| null, bytes: number \| null }` |
| `POST /debug/final_video` | `{ final_url: string, diagnostics: object }` |

### `POST /debug/head`
Request:
```json
{"url": "https://example.com/file"}
```

Security behavior:
- URL must use `http` or `https`.
- Host must resolve to public/routable IPs unless `ALLOW_PRIVATE_URL_FETCHES=true`.

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
- `image_url` and debug URL inputs must be `http(s)` and publicly routable unless `ALLOW_PRIVATE_URL_FETCHES=true`.
- `/jobs_prompt_only` rejects legacy `wan-video/wan-2.2-s2v` because it requires audio.

---

## Deployment
A Render spec is provided in `render.yaml`.

For reliable runtime packaging on Render, the build command upgrades installer tooling before installing requirements:

```bash
python -m pip install --upgrade pip setuptools wheel && pip install -r requirements.txt
```

This ensures `setuptools` (and `pkg_resources`) is present for `imageio-ffmpeg` ffmpeg resolution.

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


## Request id idempotency

`/jobs_prompt_only` and `/jobs_prompt_tts` support optional request idempotency with `request_id` (UUID).

- No `request_id`: endpoint behaves as before (new run is started).
- Existing `request_id` with `succeeded`: returns the stored response immediately (no new Replicate/ElevenLabs call).
- Existing `request_id` with `processing`: request waits and polls until completion, then returns the same stored response.
- Existing `request_id` with `failed`: returns HTTP 409 with the stored deterministic error and does not rerun.
- Invalid `request_id`: backend ignores idempotency and processes normally.

Backed by Supabase table `public.job_requests`; see migration SQL: `migrations/20260227_create_job_requests.sql`.

Canonical URL migration for metadata rows: `migrations/20260314_pet_videos_canonical_final_url.sql` adds/backfills `final_url` and `provider_video_url` for durable frontend playback/history references.
