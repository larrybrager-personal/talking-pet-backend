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

## 2026-02-28 - Proxy observability hardening
- Added Next.js proxy route scaffold for `/api/backend/job` that guarantees JSON responses and includes `x-request-id` in both response headers and response payloads.
- Added shared proxy core logic for request-id generation/forwarding, upstream JSON error passthrough, and non-JSON upstream error wrapping with bounded/sanitized previews.
- Added safe proxy logging for upstream status + request_id + sanitized preview.
- Added regression tests for upstream 500 JSON forwarding and upstream 500 text wrapping behavior.

## 2026-02-28 - Backend contract docs + response-shape guardrails
- Updated `README.md` and `MODEL_ROUTING_FRONTEND_GUIDE.md` so `/jobs_prompt_only` documents both `video_url` and `final_url` as returned by `main.py`.
- Documented canonical capability semantics in `GET /models`: `supportsAudioIn` (accepts external audio conditioning) and `generatesAudio` (may produce model-native audio).
- Added compact endpoint response-shape tables for frontend typing stability.
- Added endpoint contract tests that lock response key sets for `/jobs_prompt_only` and `/jobs_prompt_tts`, plus capability-flag presence/type checks on `/models`.

## 2026-02-28 - ffmpeg runtime robustness on Render
- Added `setuptools>=68` to prevent `pkg_resources` import errors when loading `imageio_ffmpeg` in production.
- Introduced `get_ffmpeg_path()` with imageio-first, PATH fallback, and executable validation via `ffmpeg -version`.
- Hardened muxing/compression paths to share ffmpeg resolution and return clear 500s (`ffmpeg not available in runtime`, `ffmpeg mux failed`) while logging actionable stderr diagnostics.
- Added a focused unit test for ffmpeg-path resolution with skip behavior when ffmpeg is not present in CI/runtime.

## 2026-02-28 - ffmpeg robustness follow-up for PR #41
- Tightened `get_ffmpeg_path()` import fallback handling from broad `Exception` to explicit `ImportError` plus constrained `get_ffmpeg_exe()` failure cases, with richer logs.
- Added PATH fallback via `shutil.which("ffmpeg")` before version validation.
- Updated mux/compress ffmpeg subprocess calls to avoid `capture_output=True` and reduced memory pressure with DEVNULL/PIPE stream handling.
- Ensured temp-dir cleanup cannot mask primary failures by switching to `ignore_errors=True` cleanup in ffmpeg temp workflows.
- Added deterministic unit tests for ffmpeg resolution behavior and mux HTTPException mappings.


## 2026-03-02 - Compression fallback for 502 mitigation
- Added ffmpeg compression fallback from `libx264` to `mpeg4` when the primary encoder is not available in runtime.
- Added warning logs per failed compression attempt with encoder name and sanitized stderr for faster debugging.
- Added regression tests covering fallback success and total encoder failure propagation.
