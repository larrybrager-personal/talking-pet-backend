# Update Progress Log

## Reviewed update
- Commit: `9d47520` (`Review model routing fields`)
- Scope reviewed: `main.py`, `README.md`, `MODEL_ROUTING_FRONTEND_GUIDE.md`, `tests/test_model_resolutions.py`

## What changed in that update
1. Expanded routing payload support in API request models so frontend and backend both accept camelCase fields (`hasAudio`, `selectedOverrideModel`, `modelParams`, `userContext`, `planTier`).
2. Added/expanded model metadata returned from `/models` (tier labels, duration/fps/resolution support, tunable params, and minimum plan tier metadata) to help the frontend build dynamic model selectors.
3. Added richer resolution/model payload tests to cover model-specific mapping behavior and routing normalization.
4. Updated docs to reflect current model routing semantics and frontend integration guidance.

## Review outcome
- The update improves compatibility with frontend payload shapes while preserving existing snake_case support.
- Test coverage is meaningfully improved around payload mapping and routing behavior.
- No public endpoint contract breakage observed from this review.
