# Backend to Frontend Alignment Guide

Use this file as the backend contract reference inside the frontend repo.

## What the backend does

The backend accepts one public pet image, a short prompt, and optionally TTS text. It then:

1. Chooses or validates a Replicate video model.
2. Normalizes the request to values that model actually supports.
3. Generates video, and optionally synthesizes speech with ElevenLabs.
4. Uploads the playback-ready assets to Supabase Storage.
5. Returns public URLs for the frontend to render.

The frontend should treat the backend as the source of truth for model availability, plan gating, defaults, and normalized settings.

## Frontend-safe endpoints

- `GET /models`: fetch the full model catalog and UI metadata.
- `POST /resolve_model`: preview which model and settings the backend will use.
- `POST /jobs_prompt_only`: generate a silent video.
- `POST /jobs_prompt_tts`: generate TTS audio and a final talking-video artifact.

## Canonical request shape

The backend accepts both snake_case and frontend camelCase for the main generation endpoints.

Recommended frontend keys:

```json
{
  "imageUrl": "https://example.com/pet.jpg",
  "prompt": "A friendly dog smiles and blinks naturally.",
  "text": "Hello there!",
  "voiceId": "eleven-voice-id",
  "seconds": 6,
  "resolution": "768p",
  "quality": "fast",
  "fps": 24,
  "selectedOverrideModel": "wan-video/wan2.6-i2v-flash",
  "modelParams": {"fps": 24},
  "userContext": {
    "id": "00000000-0000-0000-0000-000000000000",
    "planTier": "creator"
  },
  "requestId": "11111111-1111-1111-1111-111111111111"
}
```

Notes:

- `text` and `voiceId` are only used on `POST /jobs_prompt_tts`.
- `selectedOverrideModel` is optional. If omitted, the backend routes by `quality`.
- `modelParams` is filtered against an allowlist per model.
- `requestId` enables idempotency when it is a valid UUID.

## What `GET /models` returns

`GET /models` is the frontend's source of truth for the model picker.

Each entry in `supported_models` now includes:

- `slug`: canonical model slug.
- `name`: display label.
- `tier`: routing bucket such as `fast`, `budget`, `premium`, or `legacy`.
- `quality_label`: backend quality intent associated with the model.
- `blurb`: short UI description.
- `default_params`: backend defaults before request overrides.
- `supported_durations`
- `supported_resolutions`
- `supported_fps`
- `tunable_params`: typed tunables safe to surface in advanced controls.
- `legacy_aliases`: older slugs still accepted and normalized by the backend.
- `available_job_types`: `prompt_only`, `prompt_tts`, or both.
- `min_plan_tier`
- `runnable`
- `capabilities`

Important capability flags:

- `supportsAudioIn`: the model accepts externally supplied audio.
- `generatesAudio`: the model may generate its own audio track.
- `requiresAudioInput`: the model cannot be used from `POST /jobs_prompt_only`.

Frontend rule:

- Filter prompt-only model choices by `available_job_types` or `capabilities.requiresAudioInput`.

## How routing works

If the frontend does not force a model override, the backend routes from `quality` plus plan tier:

- `fast` prefers `wan-video/wan2.6-i2v-flash`
- `balanced` prefers `wan-video/wan-2.6-i2v`
- `cheap` prefers `bytedance/seedance-1-pro-fast`
- `quality` prefers the highest-quality model allowed by the user's plan

Plan tier can further reduce the final resolution or reject an override if the selected model is not allowed.

## Why `POST /resolve_model` matters

Use `POST /resolve_model` before submit when the UI needs a preview of the actual backend decision.

It returns:

- `model` / `resolved_model_slug`
- `plan_tier`
- `meta`
- `resolved`
- `resolved_defaults`

The frontend should treat `resolved` and `resolved_defaults` as the values that will really be used unless the user changes the request again.

## Backend normalization rules

The backend exposes a unified request contract, but individual Replicate models require different payload formatting internally.

Model-family examples:

- Wan 2.6: duration stays in seconds, resolution passes through, FPS can be sent.
- Wan 2.2 frame models: duration becomes `num_frames`, and FPS maps to `frames_per_second`.
- Kling: resolution is converted into aspect ratio, and `1080p` forces `mode=pro`.
- PixVerse: resolution is sent through the provider `quality` field.
- Seedance: unsupported resolutions are normalized down to provider-supported values.
- VEED Fabric and Wan 2.2 S2V: audio is required, so they are TTS-only from the frontend.

The frontend should not build provider-specific payloads itself. Send the unified backend payload and let the backend perform the translation.

## Final URL behavior

- `POST /jobs_prompt_only`: returns `video_url` and `final_url`. Use `final_url` for playback.
- `POST /jobs_prompt_tts`: returns `audio_url`, `video_url`, and `final_url`. Use `final_url` for playback.

`video_url` is the raw provider output.
`final_url` is the backend-uploaded playback artifact and should be treated as canonical.

## Error handling expectations

- `400`: bad input, unsupported model, incompatible override, too-long TTS text, invalid tunables.
- `401` or `403`: auth or plan gating issues.
- `500` or `502`: backend or upstream provider failure.

Recommended frontend behavior:

- Show actionable copy for `400`.
- Show upgrade or permission messaging for `403`.
- Offer retry for `500` and `502`.

## Recommended frontend flow

1. Load `GET /models` on app start or cache it with a TTL.
2. Filter model options based on job type and plan.
3. Call `POST /resolve_model` when the user changes quality, resolution, duration, or explicit model.
4. Submit `POST /jobs_prompt_only` or `POST /jobs_prompt_tts`.
5. Render `final_url` as the playback asset.
