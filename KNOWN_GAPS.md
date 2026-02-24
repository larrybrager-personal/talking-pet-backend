# Known Gaps / Follow-ups

- Add stronger validation for tunable param value ranges/types (currently key-based allowlist only).
- Add dedicated tests for Supabase profile tier lookup success/failure paths with mocked HTTP client.
- Consider extracting resolution normalization to a reusable utility and adding per-model mapping tests.
- Evaluate whether `wan-video/wan-2.2-s2v` should be auto-routed in select audio-first scenarios; currently manual override only.
- Add API docs examples for new request fields (`quality`, `fps`, `model_override`, `model_params`, `user_context.plan_tier`).
