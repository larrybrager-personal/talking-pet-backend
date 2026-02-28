-- Idempotency table for talking-pet job endpoints.
-- Safe to run once in Supabase SQL editor or migration pipeline.

create table if not exists public.job_requests (
  request_id uuid primary key,
  user_id uuid null,
  endpoint text not null,
  status text not null check (status in ('processing', 'succeeded', 'failed')),
  response_payload jsonb null,
  error_payload jsonb null,
  response_status integer null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_job_requests_user_created_at
  on public.job_requests (user_id, created_at desc);

create or replace function public.set_job_requests_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists trg_job_requests_updated_at on public.job_requests;

create trigger trg_job_requests_updated_at
before update on public.job_requests
for each row
execute function public.set_job_requests_updated_at();
