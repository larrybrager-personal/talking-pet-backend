-- Enforce async enqueue idempotency for request_id within endpoint+user scope.
-- `coalesce` keeps anonymous (null user_id) requests deduplicated too.

create unique index if not exists idx_async_jobs_request_scope_unique
  on public.async_jobs (request_id, endpoint, coalesce(user_id, '00000000-0000-0000-0000-000000000000'::uuid))
  where request_id is not null;
