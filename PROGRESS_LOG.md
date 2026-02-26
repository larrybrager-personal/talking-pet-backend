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

