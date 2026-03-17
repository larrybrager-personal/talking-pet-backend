-- Enforce async enqueue idempotency for request_id within endpoint+user scope.
-- `coalesce` keeps anonymous (null user_id) requests deduplicated too.
-- Guard against fresh databases where async_jobs is created by a later migration.

do $$
begin
  if to_regclass('public.async_jobs') is null then
    raise notice 'Skipping idx_async_jobs_request_scope_unique: public.async_jobs does not exist yet';
    return;
  end if;

  create unique index if not exists idx_async_jobs_request_scope_unique
    on public.async_jobs (request_id, endpoint, coalesce(user_id, '00000000-0000-0000-0000-000000000000'::uuid))
    where request_id is not null;
end
$$;
