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
5. Render returned URLs (`video_url`, `audio_url`, `final_url`).

## 2) Tier and route defaults

Routing defaults:
- `fast` → `wan-video/wan2.6-i2v-flash`
- `premium` → `kwaivgi/kling-v2.6`
- `budget` → `bytedance/seedance-1-pro-fast`
- `legacyFallback` → `wan-video/wan-2.2-s2v`

`default_model` is the fast route default.

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

## 7) Important UX notes
- Keep prompts concise and concrete.
- Keep TTS script short for best lip-sync and pacing.
- Do not send `wan-video/wan-2.2-s2v` to `/jobs_prompt_only` (audio-required model).
- Use returned URLs directly; backend uploads everything to Supabase Storage.

## 8) Error handling patterns
- **400**: invalid request inputs (unsupported model, too-long TTS text, invalid params).
- **401/403**: API auth enabled and token missing/invalid.
- **500**: backend configuration/service errors.

Show actionable user copy for 400 errors and retry guidance for transient provider failures.
