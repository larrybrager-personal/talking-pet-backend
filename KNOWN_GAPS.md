# Known Gaps / Follow-ups

- Add typed frontend SDK (TypeScript interfaces + runtime zod validators) generated from OpenAPI/contract snapshots to enforce the documented response-shape tables at compile time and runtime.
- Add endpoint tests for `/jobs_prompt_tts` `supportsAudioIn=false` branch to assert mux path response-shape remains stable during audio/video composition changes.
- Add frontend reference UI component for rendering `/debug/final_video` diagnostics with copy-to-clipboard support for support tickets.
- Extend final video diagnostics to include browser-playability checks (e.g., MediaSource/HTML5 video test harness) instead of transport/container checks only.
- Add redaction filters for structured logs if future debug payloads include user-provided prompt/script fields.
- Add dedicated tests for Supabase profile tier lookup success/failure paths with mocked HTTP client.
- Add explicit endpoint tests for `/jobs_prompt_only` and `/jobs_prompt_tts` that mock Replicate create calls and assert duration normalization for every model with enum-limited durations (especially Wan 2.6 family).
- Add endpoint-level assertions for resolution normalization passed into Replicate payloads by model family.
- Add API docs examples for all advanced request fields (`quality`, `fps`, `model_override`, `model_params`, `user_context.plan_tier`).
- Evaluate whether additional request correlation metadata (request IDs) should be surfaced in responses/logging.
- Evaluate if plan-tier caching should be introduced for repeated profile lookups to reduce Supabase round-trips.
- Consider consolidating quality normalization inside `model_routing` as a shared utility to remove duplicate alias logic between endpoint handlers and routing internals.
- Add integration coverage for real ffmpeg recompression path (currently unit-tested with mocks only) to validate output compatibility across source codecs.
- Consider adaptive bitrate/scale-down policy (in addition to CRF changes) for very long clips that still exceed storage targets after compression attempts.
- Expose `VIDEO_UPLOAD_TARGET_BYTES` in deployment docs/env templates so operations can align backend limits with Supabase bucket/project limits.
- Verify Replicate version-level input schemas for newly added models in production and tune defaults/ranges per latest model version docs.
- Revisit `kwaivgi/kling-v3-omni-video` once schema is confirmed; switch `runnable` to true and add payload tests.
- Add endpoint-level tests for `/jobs_prompt_only` and `/jobs_prompt_tts` covering Wan 2.5 audio-input and VEED Fabric audio-driven flow with mocked Replicate responses.
- Add endpoint compatibility tests for camelCase aliases on `/jobs_prompt_only` and `/jobs_prompt_tts` request models to mirror `/resolve_model` backward-compat behavior.

- Add endpoint-level tests for `/jobs_prompt_tts` failed-idempotency branch to verify deterministic 409 response and no rerun on stored failures.
- Consider adding stale `processing` recovery (heartbeat/lease ownership) for crashed owner requests so duplicates can eventually fail fast with clearer remediation.
