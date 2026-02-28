# Progress Log

## 2026-02-24
- Refactored model catalog out of `main.py` into `model_registry.py` with richer metadata (quality labels, blurbs, durations, fps, tunables).
- Added `model_routing.py` with legacy normalization, plan-aware intent routing, and model param allowlist filtering.
- Extended API contract:
  - `/models` now returns enriched model metadata.
  - Added `/resolve_model` to resolve model + normalized settings from user intent.
  - Updated `/jobs_prompt_only` and `/jobs_prompt_tts` to support quality/fps/model_override/model_params and automatic routing.
- Updated payload generation to merge safe, allowlisted model params and include fps when supported.
- Expanded tests for routing behavior, `/resolve_model`, enriched `/models`, and model param allowlist handling.
- Normalized frontend resolution aliases (`768p`/`1024p`) to backend-supported values (`720p`/`1080p`) during intent resolution and explicit model overrides to prevent Replicate validation failures.
- Updated Wan 2.6 model metadata to advertise supported resolutions (`720p`, `1080p`) and added tests covering resolution normalization paths.

## 2026-02-25
- Updated Wan 2.6 model metadata to align with duration enums (`5`, `10`, `15`) and max duration 15s for both `wan2.6-i2v-flash` and `wan-2.6-i2v`.
- Added shared generation-setting normalization so explicit model overrides in `/resolve_model`, `/jobs_prompt_only`, and `/jobs_prompt_tts` consistently snap unsupported durations.
- Extended tests to assert override duration normalization and updated routing expectations for Wan 2.6 duration snapping.
- Refreshed repository documentation (`README.md`, frontend routing guide, known-gaps log) so human and AI operators can follow request flow, model routing, normalization, and operational runbooks without reading source first.
- Clarified endpoint examples to include advanced routing fields and user context.

## 2026-02-26
- Extended `/debug/final_video` to optionally include compression debugging (`include_compression_debug`, optional `target_bytes`) so frontend teams can inspect CRF attempt outcomes alongside delivery/codec diagnostics.
- Added shared compression debug helper (`prepare_video_for_upload_with_debug`) to reuse the same compression path in production uploads and diagnostics.
- Updated frontend integration guide with concrete UI/API changes needed to surface backend diagnostics after final-video load failures.
- Expanded tests to cover debug endpoint compression output path.
- Added thorough final-video delivery diagnostics: HEAD/Range checks and ffprobe-based container/codec inspection helpers (`collect_video_delivery_debug`, `inspect_video_bytes`).
- Added proactive validation after final upload in both `/jobs_prompt_only` and `/jobs_prompt_tts`; requests now fail fast with actionable 502 when the returned final URL is unreachable/empty.
- Added new `/debug/final_video` endpoint to return transport diagnostics plus MP4 probe metadata for a supplied URL.
- Extended metadata tests to cover final-video diagnostics behavior and new debug endpoint output.
- Added configurable `VIDEO_UPLOAD_TARGET_BYTES` (default 9.5MB) and upload-time video size guard/compression path before Supabase uploads for both `/jobs_prompt_only` and `/jobs_prompt_tts`.
- Added progressive MP4 recompression helper using ffmpeg (`crf` 28/32/36) with actionable 400 error when still over target size.
- Added tests for compression behavior and endpoint upload calls to ensure compressed bytes are uploaded.
- Added quality normalization in `main.py` (`normalize_quality`) so legacy and UI aliases (`best`, `high`, `medium`, `low`) map to supported tiers and unknown values safely default to `fast`.
- Relaxed request schema quality typing from strict literals to `str` in `/resolve_model`, `/jobs_prompt_only`, and `/jobs_prompt_tts` request models to avoid 422 responses for legacy quality values.
- Applied normalized quality handling across `/resolve_model` and `_resolve_job_model` so downstream routing and resolved payloads are consistent.
- Extended `/resolve_model` response contract to include `resolved_model_slug` while preserving existing `model` for backward compatibility.
- Updated `/models` response mapping to expose tunable parameter `description` (derived from `help`) without mutating global model registry metadata.
- Added endpoint tests covering legacy `quality="best"` normalization, `resolved_model_slug` presence, and `tunable_params[].description` alias behavior.
- Centralized quality normalization in `model_routing.normalize_quality` and reused it in both intent routing and FastAPI handlers to remove duplicate alias logic.
- Hardened model tunable param filtering in `apply_allowed_model_params` with type/range/step/enum validation instead of key-only allowlisting.
- Replaced blocking `time.sleep` in Replicate polling loop with non-blocking `await asyncio.sleep` to avoid pausing the event loop during long-running prediction polls.
- Expanded tests to cover quality normalization utility behavior and model-param validation edge cases (boolean, enum, numeric range, numeric step).


## 2026-02-27
- Added Pydantic alias compatibility for `/resolve_model` request parsing so snake_case and legacy camelCase keys are both accepted (`userContext`, `planTier`, `hasAudio`, `selectedOverrideModel`, `modelParams`) while keeping snake_case internal fields.
- Added request-model config for pydantic v1/v2 compatibility with populate-by-name and ignored extra fields for backward-compatible payload handling.
- Updated `/resolve_model` responses to always include a top-level `plan_tier` in both explicit override and automatic routing flows.
- Added endpoint tests to verify camelCase payload acceptance and top-level `plan_tier` presence.

## 2026-02-27
- Added backend idempotency for `/jobs_prompt_only` and `/jobs_prompt_tts` keyed by optional `request_id`, including Supabase-backed single-flight dedupe, deterministic failed-request handling, and polling behavior for duplicate in-flight requests.
- Added Supabase migration SQL for `job_requests` idempotency table and update timestamp trigger.
- Added unit tests for deduped-success short-circuit, owner success update, and processing-to-succeeded polling behavior.
- Updated README with idempotency request/response behavior and env controls (`IDEMPOTENCY_POLL_INTERVAL_SEC`, `IDEMPOTENCY_MAX_WAIT_SEC`).


## 2026-02-27
- Updated idempotency Supabase PATCH/write paths to the payload-based schema only: `response_payload` and `error_payload` (plus `response_status`) in `update_job_request`.
- Updated idempotent duplicate polling to read `response_payload` on success and surface `error_payload.message` on failure in `await_existing_job_request`.
- Updated idempotency test fixtures to match payload-based columns and verified behavior with unit tests.

## 2026-02-28
- Fixed an unhandled model-resolution failure path by translating `ValueError` from routing resolution into `400` responses in `/resolve_model` and shared job model resolution, preventing opaque `500` errors for invalid resolution/model-plan combinations.
- Added structured unexpected-error logging helper for `/jobs_prompt_only` and `/jobs_prompt_tts` to capture endpoint, request_id, user_id, model, and exception type without logging request payloads or secrets.
- Removed duplicate compression diagnostics assignment in `/jobs_prompt_only` final-video diagnostics to keep debug payloads clean and deterministic.
- Validated updates with formatting, compile checks, and focused routing/metadata tests.

## 2026-02-28
- Added a Next.js proxy route handler scaffold at `app/api/backend/job/route.js` with correlation-aware forwarding via `x-request-id` and guaranteed JSON responses on both success and failure.
- Added proxy core helper (`app/api/backend/job/proxy-core.cjs`) to centralize request-id generation, upstream JSON passthrough behavior, bounded/sanitized non-JSON error previews, and safe observability logs (`request_id`, upstream status, preview).
- Added regression tests (`tests_js/proxy_route_error_forwarding.test.cjs`) covering upstream 500 JSON passthrough and upstream 500 text wrapping into stable JSON with `request_id`.
