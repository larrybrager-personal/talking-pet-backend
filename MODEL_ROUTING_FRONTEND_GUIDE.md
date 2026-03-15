# Frontend Integration Guide: Model Routing and Job Flows

Use this guide when wiring a UI or agent client to the backend model-routing flow.

## 1) Recommended frontend flow

1. Call `GET /models` once on app load (or cache with TTL).
2. Let user choose either:
   - Simple quality intent (`fast` / `balanced` / `cheap` / `quality`) or
   - Explicit model override (advanced mode)
3. (Optional but recommended) Call `POST /resolve_model` to preview normalized settings.
4. Submit final generation request via:
   - `POST /jobs_prompt_only`, or
   - `POST /jobs_prompt_tts`
   - Frontend camelCase request keys are accepted on both job endpoints (`imageUrl`, `voiceId`, `selectedOverrideModel`, `modelParams`, `userContext`, `requestId`)
5. Render returned URLs (`video_url`, `audio_url`, `final_url`) with `final_url` as the canonical playback URL.

## 2) Tier and route defaults

Routing defaults:
- `fast` → `wan-video/wan2.6-i2v-flash`
- `premium` → `kwaivgi/kling-v2.6`
- `budget` → `bytedance/seedance-1-pro-fast`
- `legacyFallback` → `wan-video/wan-2.2-s2v`

`default_model` is the fast route default.

Each model entry also includes frontend-facing contract helpers:
- `slug`: canonical model id to store and submit.
- `default_params`: backend defaults before request overrides.
- `legacy_aliases`: old slugs still accepted and normalized.
- `available_job_types`: whether the model can be used for `prompt_only`, `prompt_tts`, or both.


## 3.1) Capability semantics (canonical)

In `GET /models`, interpret capability flags as:
- `supportsAudioIn`: model accepts external audio conditioning input from the request.
- `generatesAudio`: model may produce its own audio track without external audio input.
- `requiresAudioInput`: model cannot be used from `POST /jobs_prompt_only`.

These two booleans are independent and should not be conflated in frontend logic.

## 3) Legacy slug normalization

The backend normalizes older slugs so old data/UI values keep working:
- `minimax/hailuo-02` → `minimax/hailuo-2.3`
- `kwaivgi/kling-v2.1` → `kwaivgi/kling-v2.6`
- `bytedance/seedance-1-lite` → `bytedance/seedance-1-pro-fast`
- `wan-video/wan-2.1` → `wan-video/wan2.6-i2v-flash`

Unknown slugs fall back to the fast default during intent routing, but explicit invalid model submissions may still return 400 if they cannot be normalized.

## 4) Normalization behavior to expect

The backend will normalize request settings to model-supported values:
- Durations may snap to supported enums (e.g., Wan 2.6 family uses 5/10/15).
- Resolution aliases normalize where needed (`768p`→`720p`, `1024p`→`1080p`).
- FPS is accepted only for models that support it.
- `model_params` are filtered to an allowlist for the chosen model.

Treat `resolved` values from `POST /resolve_model` as source-of-truth preview values.
Use `resolved_defaults` from `POST /resolve_model` as the backend-filtered parameter set that will be passed to Replicate input shaping.

## 5) Prompt-only request example

```json
{
  "image_url": "https://example.com/pet.jpg",
  "prompt": "A happy dog smiles and blinks naturally.",
  "seconds": 6,
  "resolution": "768p",
  "quality": "fast",
  "fps": 24,
  "model_override": null,
  "model_params": {"fps": 24},
  "user_context": {"id": "uuid", "plan_tier": "free"}
}
```

## 6) Prompt+TTS request example

```json
{
  "image_url": "https://example.com/pet.jpg",
  "prompt": "A calm cat looks into camera and lip-syncs speech.",
  "text": "Hi, I'm Luna. Nice to meet you.",
  "voice_id": "eleven-voice-id",
  "seconds": 6,
  "resolution": "768p",
  "quality": "quality",
  "model_override": null,
  "model_params": {"mode": "pro"},
  "user_context": {"id": "uuid", "plan_tier": "studio"}
}
```

## 6.1) Response-shape table (for frontend typing)

| Endpoint | Response shape |
|---|---|
| `GET /health` | `{ ok: boolean }` |
| `GET /models` | `{ supported_models: Record<string, ModelMeta>, default_model: string, routing_defaults: RoutingDefaults }` |
| `POST /resolve_model` | `{ model: string, resolved_model_slug: string, plan_tier: string, meta: object, resolved: { seconds: number, resolution: string, fps: number \| null, quality: string }, resolved_defaults: object }` |
| `POST /jobs_prompt_only` | `{ video_url: string, final_url: string }` |
| `POST /jobs_prompt_tts` | `{ audio_url: string, video_url: string, final_url: string }` |
| `POST /debug/head` | `{ status: number, content_type: string \| null, bytes: number \| null }` |
| `POST /debug/final_video` | `{ final_url: string, diagnostics: object }` |

`final_url` semantics:
- `/jobs_prompt_only`: always a backend-uploaded Supabase artifact.
- `/jobs_prompt_tts` + `supportsAudioIn=true`: backend re-uploads generated MP4 as `final_url` (no mux step).
- `/jobs_prompt_tts` + `supportsAudioIn=false`: backend muxes video + TTS audio and uploads a new MP4 as `final_url`.

## 7) Important UX notes
- Keep prompts concise and concrete.
- Keep TTS script short for best lip-sync and pacing.
- Do not send models with `capabilities.requiresAudioInput=true` to `/jobs_prompt_only`.
- Use returned URLs directly; backend uploads everything to Supabase Storage.

## 8) Error handling patterns
- **400**: invalid request inputs (unsupported model, too-long TTS text, invalid params).
- **401/403**: API auth enabled and token missing/invalid.
- **500**: backend configuration/service errors.

Show actionable user copy for 400 errors and retry guidance for transient provider failures.


## 9) Frontend changes needed for actionable debug logs

When a generation call fails with status `502` and message like:
`Final video could not be validated for playback. Use /debug/final_video for details.`

Implement this client flow:
1. Capture the returned `final_url` from a successful response (or from your job state if available).
2. Call `POST /debug/final_video` with:
   ```json
   {
     "url": "<final_url>",
     "include_compression_debug": true
   }
   ```
3. Render a developer-only diagnostics panel with these fields:
   - delivery: `head_status`, `content_type`, `content_length`, `range_status`, `accept_ranges`, `content_range`
   - container/codec: `probe.is_valid_mp4`, `probe.container`, `probe.video_codec`, `probe.audio_codec`, `probe.width`, `probe.height`, `probe.duration`
   - compression: `compression.target_bytes`, `compression.original_bytes`, `compression.final_bytes`, `compression.meets_target`, plus each `compression.attempts[]` row (`crf`, `output_bytes`, `improved`, `error`)

### Minimal frontend pseudo-code

```js
async function loadFinalVideoDiagnostics(base, finalUrl) {
  const res = await fetch(`${base}/debug/final_video`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      url: finalUrl,
      include_compression_debug: true,
    }),
  });
  const data = await res.json();
  return data;
}
```

### Does this include debugging of video compression?
Yes. `include_compression_debug: true` adds compression-attempt diagnostics so the UI can verify whether the uploaded video was already under target or required CRF passes, and whether it still missed the configured size target.
