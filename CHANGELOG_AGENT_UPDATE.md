# Agent Update Log

## Summary
- Added plan-tier model access (`min_plan_tier`) to model catalog entries.
- Enforced backend plan-based resolution caps (free 480p, creator 768p, studio/ultimate 1080p).
- Updated routing and override paths to enforce model/plan compatibility.
- Kept FPS behavior strict to model support and param mapping.
- Extended `/models` metadata to include `min_plan_tier`.
- Expanded tests to cover tier inheritance, cap behavior, override enforcement, and FPS validation.

## 2026-02-27 - Replicate catalog expansion
- Added nine new runnable Replicate models across Wan 2.2/2.5, Hailuo, PixVerse, Veo, and VEED Fabric.
- Added one experimental catalog-only model (`kwaivgi/kling-v3-omni-video`) marked `runnable: false`.
- Extended payload building to support frame-count models (`num_frames`) with FPS-aware conversion and model-specific key mapping.
- Updated muxing to explicitly map video stream from source video and audio stream from ElevenLabs audio (`-map 0:v:0 -map 1:a:0`).
- Added focused unit tests for new payload mappings, Wan frame conversion, and mux command stream mapping.

## 2026-02-27 - Resolve model payload compatibility
- Added `/resolve_model` request alias support for both snake_case and legacy camelCase fields.
- Added pydantic v1/v2-compatible request config (`populate by name`, `extra=ignore`) for resilient API parsing.
- Added top-level `plan_tier` to `/resolve_model` responses for both override and routed selections.
- Added tests validating camelCase request payload support and guaranteed `plan_tier` response presence.
