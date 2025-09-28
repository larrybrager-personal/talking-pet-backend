# Change Log

## Current Update
- Added a Supabase PostgREST helper to persist generated pet video metadata alongside storage keys.
- Updated prompt-only and TTS job handlers to invoke the helper, ensuring uploads roll back on insert failure.
- Extended async unit coverage for the new helper and handler integration points.

## Previous Updates
- Added optional `user_context` payload handling so generated assets are scoped to authenticated users.
- Persisted prompt-only and speech-to-video outputs to Supabase before returning URLs to clients.
- Introduced helper utilities and unit tests covering storage prefix validation.
