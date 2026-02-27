# Agent Update Log

## Summary
- Added plan-tier model access (`min_plan_tier`) to model catalog entries.
- Enforced backend plan-based resolution caps (free 480p, creator 768p, studio/ultimate 1080p).
- Updated routing and override paths to enforce model/plan compatibility.
- Kept FPS behavior strict to model support and param mapping.
- Extended `/models` metadata to include `min_plan_tier`.
- Expanded tests to cover tier inheritance, cap behavior, override enforcement, and FPS validation.
