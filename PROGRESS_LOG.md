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
