# Known Gaps / Follow-Ups

- [ ] Add integration coverage that exercises full Supabase upload + Replicate video persistence end-to-end once service mocks are available.
- [ ] Investigate adding request correlation IDs to outbound Replicate and Supabase calls for improved observability.
- [ ] Capture and surface Supabase cleanup failures so atomic rollback issues are observable in monitoring.
- [ ] Reintroduce structured storage key persistence once the Supabase schema supports it to aid future asset lifecycle management.
- [ ] Replace the shared secret auth toggle with Supabase JWT validation once frontend session plumbing is available.
- [ ] Confirm Kling v2.1 1080p "pro" mode output quality and aspect ratio behavior across additional prompt presets when Replicate credits are available.
