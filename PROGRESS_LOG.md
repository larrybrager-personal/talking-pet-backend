# Change Log

## Current Update
- Added an opt-in bearer token auth guard that protects every endpoint when `API_AUTH_ENABLED=true`.
- Documented the new auth environment variables and introduced unit coverage for the guard logic.

## Previous Updates
- Updated Supabase metadata persistence to drop the deprecated `storage_key` field and rely on the public `video_url`, avoiding schema mismatches.
- Refreshed job handler and helper unit tests to reflect the simplified persistence contract.
- Added a Supabase PostgREST helper to persist generated pet video metadata alongside storage keys.
- Updated prompt-only and TTS job handlers to invoke the helper, ensuring uploads roll back on insert failure.
- Extended async unit coverage for the new helper and handler integration points.
- Added optional `user_context` payload handling so generated assets are scoped to authenticated users.
- Persisted prompt-only and speech-to-video outputs to Supabase before returning URLs to clients.
- Introduced helper utilities and unit tests covering storage prefix validation.
