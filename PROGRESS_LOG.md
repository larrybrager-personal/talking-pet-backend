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

- Standardized docs for endpoint contract parity with implementation: `/jobs_prompt_only` now documented with `{video_url, final_url}` and clarified `final_url` lifecycle in both jobs flows.
- Added canonical model capability definitions (`supportsAudioIn`, `generatesAudio`) to docs for reliable frontend interpretation.
- Added response-shape tables to README + frontend guide to support stable client-side typing.
- Added endpoint contract tests to lock response keys for `/jobs_prompt_only`, `/jobs_prompt_tts`, and capability-flag presence/types in `/models`.

## 2026-02-28
- Fixed `/debug/final_video` response contract to always return an envelope `{ final_url, diagnostics }` instead of returning raw diagnostics directly, aligning implementation with documented frontend typing tables.
- Updated final-video diagnostics tests to assert the wrapped response shape and added coverage for the download-error branch so failures still return the same envelope.
- Synced README response-shape table to include `/debug/final_video` for contract visibility in primary docs.

## 2026-02-28
- Fixed Render `/jobs_prompt_tts` runtime failure caused by missing `pkg_resources` by adding `setuptools>=68` while keeping `imageio-ffmpeg==0.4.9`.
- Added cached `get_ffmpeg_path()` helper that prefers `imageio_ffmpeg.get_ffmpeg_exe()`, falls back to `ffmpeg` on PATH, and validates availability via `-version` with clear HTTP 500 errors.
- Updated `mux_video_audio()` and `_compress_video_bytes()` to use shared ffmpeg resolution, improved mux error handling for `CalledProcessError`/`FileNotFoundError`, and log stderr for debugging without leaking internals to API clients.
- Added unit coverage for `get_ffmpeg_path()` with runtime-aware skip when ffmpeg is unavailable.

## 2026-02-28
- Polished ffmpeg fallback robustness: `get_ffmpeg_path()` now catches `ImportError` for `imageio_ffmpeg` import, logs actionable fallback context, then resolves PATH ffmpeg via `shutil.which`.
- Hardened temp-directory cleanup in mux/compress/final-video probe paths with `shutil.rmtree(..., ignore_errors=True)` so cleanup never masks root-cause failures.
- Reduced ffmpeg subprocess memory overhead by using `stdout=DEVNULL` + `stderr=PIPE` (no `capture_output=True`) and preserved stable API errors (`ffmpeg mux failed`, `ffmpeg not available in runtime`).
- Closed mux output file deterministically with context manager before temp cleanup.
- Added hermetic unit tests for ffmpeg resolution priority/fallback and mux HTTP 500 error mapping for ffmpeg failure and missing-runtime scenarios.

## 2026-03-01
- Hardened ffmpeg resolution by broadening `imageio_ffmpeg` import fallback handling in `get_ffmpeg_path()` and removing warning tracebacks for expected fallback paths.
- Added a targeted warning hint for `pkg_resources` import errors to recommend installing `setuptools`.
- Added startup runtime smoke check (`run_ffmpeg_runtime_smoke_check`) so ffmpeg availability issues are logged early during app boot.
- Updated deployment packaging (`requirements.txt`, `render.yaml`, README deployment note) to reliably install/upgrade `setuptools` and `wheel` on Render.
- Extended ffmpeg tests to cover generic import failures, missing PATH fallback behavior, and smoke-check logging outcomes.

## 2026-03-01
- Updated runtime dependency pin from `imageio-ffmpeg==0.4.9` to `imageio-ffmpeg==0.6.0` to avoid legacy `pkg_resources` import paths that surface as Render runtime warnings/errors when setuptools metadata support is unavailable.
- Kept dependency footprint minimal by removing explicit `setuptools`/`wheel` runtime pins from `requirements.txt` and relying on Render build toolchain bootstrap already defined in `render.yaml`.


## 2026-03-02
- Fixed video compression robustness for Render/runtime environments where `libx264` is unavailable by adding a fallback ffmpeg encode path (`mpeg4` + AAC) in `_compress_video_bytes`.
- Preserved existing API behavior (`prepare_video_for_upload_with_debug`) while preventing unexpected compression-stage 500s that surfaced as upstream 502s.
- Added unit tests for compression fallback success and all-encoders-fail handling in `tests/test_video_compression.py`.

## 2026-03-14
- Unified job endpoint request parsing with `RequestModel` alias compatibility used by `/resolve_model` so `/jobs_prompt_only` and `/jobs_prompt_tts` now accept both snake_case and camelCase payload variants.
- Added explicit compatibility mapping for legacy `selectedOverrideModel` on job endpoints while preserving snake_case compatibility.
- Updated metadata persistence contract so `insert_pet_video` stores `final_url` as canonical playback URL and tracks raw provider output in `provider_video_url`; `video_url` remains a backward-compatible mirror of `final_url`.
- Added migration `20260314_pet_videos_canonical_final_url.sql` to add/backfill canonical playback columns for existing rows.
- Expanded endpoint contract tests for job response shapes, alias compatibility, backward-compatible snake_case inputs, and canonical URL persistence semantics.
- Updated frontend-facing docs (`README.md`, `MODEL_ROUTING_FRONTEND_GUIDE.md`) with explicit alias acceptance and canonical playback semantics.

## 2026-03-14
- Hardened migration `20260314_pet_videos_canonical_final_url.sql` for fresh/ephemeral databases by wrapping `pet_videos` backfill updates and index creation in a `to_regclass('public.pet_videos')` guard inside a DO block.
- Preserved forward-only idempotency so canonical column adds still use `alter table if exists ... add column if not exists` while skipping unsafe statements when the table is absent.

## 2026-03-16
- Fixed migration ordering safety for async job idempotency index creation by wrapping `20260316_async_jobs_request_id_scope.sql` in a `to_regclass('public.async_jobs')` guard, preventing failures on fresh environments where the table is created by a later migration file.
- Added the same `idx_async_jobs_request_scope_unique` index creation to `20260316_create_async_jobs.sql` so new databases always end with the intended uniqueness constraint even if the guard migration runs first.
- Preserved forward-only/idempotent behavior with `create ... if not exists` and no schema contract changes to existing endpoints.

