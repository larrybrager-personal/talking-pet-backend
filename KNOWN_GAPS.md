# Known Gaps / Follow-Ups

- [ ] Verify the exact Replicate input schemas for all newly added slugs (`wan2.6`, `kling-v2.6`, `hailuo-2.3`, `seedance-1-pro*`) in a live environment and tune per-model payload adapters if fields differ.
- [ ] Decide whether the frontend should expose all optional quality variants by default (`wan-2.6-i2v`, `seedance-1-pro`, `kling-v2.5-turbo-pro`) or keep a simplified curated subset.
- [ ] Add persistence-time normalization for historical records that are read directly from DB in future analytics/reporting paths.
- [ ] Add integration coverage for model normalization + submission flow against mocked Replicate responses.
- [ ] Add request IDs and structured metrics around model routing decisions and normalization hits for observability.
- [ ] Run a manual smoke test for prompt-only and prompt+tts across at least one model in each tier once Replicate credits are available.
