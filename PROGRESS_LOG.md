# Change Log

## Current Update
- Promoted Wan v2.2 S2V as the default image-to-video model across the API, documentation, and tests so new jobs target the higher-quality model by default.

## Previous Updates
- Switched the default image-to-video model to Wan v2.1, ensured the Replicate payload carries the `wan2.1` format flag, and verified Hailuo can still be targeted explicitly.
- Surfaced 1080p support for Replicate models in both request payloads and the `/models` metadata response so the frontend can target higher resolutions reliably.
- Added unit coverage ensuring Kling pro mode toggles for 1080p and that supported resolutions include the new option.
- Added an opt-in bearer token auth guard that protects every endpoint when `API_AUTH_ENABLED=true`.
- Documented the new auth environment variables and introduced unit coverage for the guard logic.
- Updated Supabase metadata persistence to drop the deprecated `storage_key` field and rely on the public `video_url`, avoiding schema mismatches.
- Refreshed job handler and helper unit tests to reflect the simplified persistence contract.
- Added a Supabase PostgREST helper to persist generated pet video metadata alongside storage keys.
- Updated prompt-only and TTS job handlers to invoke the helper, ensuring uploads roll back on insert failure.
- Extended async unit coverage for the new helper and handler integration points.
- Added optional `user_context` payload handling so generated assets are scoped to authenticated users.
- Persisted prompt-only and speech-to-video outputs to Supabase before returning URLs to clients.
- Introduced helper utilities and unit tests covering storage prefix validation.
