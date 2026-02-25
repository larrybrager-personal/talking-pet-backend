# Known Gaps / Follow-ups

- Add stronger validation for tunable param value ranges/types (currently key-based allowlist only).
- Add dedicated tests for Supabase profile tier lookup success/failure paths with mocked HTTP client.
- Consider extracting resolution normalization to a reusable utility and adding per-model mapping tests.
- Evaluate whether `wan-video/wan-2.2-s2v` should be auto-routed in select audio-first scenarios; currently manual override only.
- Add API docs examples for new request fields (`quality`, `fps`, `model_override`, `model_params`, `user_context.plan_tier`).
- Add endpoint-level tests for `/jobs_prompt_only` and `/jobs_prompt_tts` verifying normalized resolutions passed into Replicate create payloads for each supported model family.
- Add explicit endpoint tests for `/jobs_prompt_only` and `/jobs_prompt_tts` that mock Replicate create calls and assert duration normalization for every model with enum-limited durations (especially `wan-video/wan2.6-i2v-flash`).

