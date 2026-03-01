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

## 2026-02-28 Proxy Observability Follow-ups
- Wire this proxy implementation into the actual frontend deployment repository if `/api/backend/job` is owned outside this backend repo.
- Expand proxy tests to cover success-path `request_id` propagation and fallback generation when incoming headers are missing.
- Add a shared structured logger adapter (instead of `console`) so logs can be shipped consistently to the production log pipeline with severity and trace context.

## 2026-02-28 Debug Final Video Contract Follow-ups
- Add explicit Pydantic `response_model` for `/debug/final_video` so OpenAPI and generated clients enforce `{ final_url, diagnostics }` at schema level instead of relying only on docs/tests.
- Consider splitting `diagnostics` into typed sub-objects (`delivery`, `probe`, `compression`) to reduce frontend `object` casts and improve generated SDK ergonomics.

## 2026-03-01 FFmpeg Runtime Follow-ups
- Consider adding a dedicated `/debug/runtime` endpoint that surfaces sanitized dependency/bin readiness checks (ffmpeg, setuptools/pkg_resources availability) for faster ops triage.
- Add CI coverage for startup event execution to ensure runtime smoke checks continue to run after FastAPI lifecycle refactors.

## 2026-03-01 Dependency Follow-ups
- After next Render deploy, confirm logs no longer emit `imageio_ffmpeg import failed ... No module named 'pkg_resources'` and capture a baseline startup log sample.
- If any environment still reports `pkg_resources` errors, pin Render runtime Python image and add an automated startup self-check that imports `imageio_ffmpeg` and records version metadata.
