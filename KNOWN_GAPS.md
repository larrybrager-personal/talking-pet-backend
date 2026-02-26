# Known Gaps / Follow-ups

- Extend final video diagnostics to include browser-playability checks (e.g., MediaSource/HTML5 video test harness) instead of transport/container checks only.
- Add redaction filters for structured logs if future debug payloads include user-provided prompt/script fields.
- Add dedicated tests for Supabase profile tier lookup success/failure paths with mocked HTTP client.
- Add explicit endpoint tests for `/jobs_prompt_only` and `/jobs_prompt_tts` that mock Replicate create calls and assert duration normalization for every model with enum-limited durations (especially Wan 2.6 family).
- Add endpoint-level assertions for resolution normalization passed into Replicate payloads by model family.
- Add API docs examples for all advanced request fields (`quality`, `fps`, `model_override`, `model_params`, `user_context.plan_tier`).
- Evaluate whether additional request correlation metadata (request IDs) should be surfaced in responses/logging.
- Evaluate if plan-tier caching should be introduced for repeated profile lookups to reduce Supabase round-trips.
- Consider consolidating quality normalization inside `model_routing` as a shared utility to remove duplicate alias logic between endpoint handlers and routing internals.
- Add stricter URL validation for `image_url` and `HeadRequest.url` to reject malformed/unsafe schemes at request parsing time.
- Add integration coverage for real ffmpeg recompression path (currently unit-tested with mocks only) to validate output compatibility across source codecs.
- Consider adaptive bitrate/scale-down policy (in addition to CRF changes) for very long clips that still exceed storage targets after compression attempts.
- Expose `VIDEO_UPLOAD_TARGET_BYTES` in deployment docs/env templates so operations can align backend limits with Supabase bucket/project limits.
