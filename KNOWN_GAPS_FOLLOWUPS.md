# Known Gaps / Follow-ups

- Consider centralizing resolution normalization in a single shared helper (currently duplicated between routing and endpoint-level resolution handling).
- Consider adding explicit error code taxonomy for upgrade-required vs invalid-input failures.
- Add dedicated tests for `/jobs_prompt_only` and `/jobs_prompt_tts` override enforcement paths (current additions are focused on `/resolve_model` and routing helpers).
- Optionally expose plan caps directly in `/models` response (e.g. `plan_max_resolution`) for better frontend UX hints.
- Consider storing structured failure metadata in `error_payload` (e.g., `type`, `status_code`, `retryable`) to improve client-side remediation while keeping user-facing messages safe.


## 2026-02-28 Follow-ups
- Add request-scoped correlation IDs (from header or generated UUID) to all log lines, including downstream Supabase/Replicate calls, to speed up production tracing across async boundaries.
- Add tests that explicitly assert `ValueError` from `resolve_model_for_intent` maps to HTTP 400 in `/resolve_model` and both job endpoints.
- Consider moving logger configuration to structured JSON output for production environments to improve searchability in log aggregation tools.
