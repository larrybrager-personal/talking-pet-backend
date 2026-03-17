-- Async background job queue for talking-pet backend.
-- Safe to run once in Supabase SQL editor or migration pipeline.

create extension if not exists pgcrypto;

create table if not exists public.async_jobs (
  id uuid primary key default gen_random_uuid(),
  kind text not null check (kind in ('prompt_only', 'prompt_tts')),
  endpoint text not null,
  status text not null check (status in ('queued', 'processing', 'succeeded', 'failed')),
  request_id uuid null,
  user_id uuid null,
  request_payload jsonb not null,
  response_payload jsonb null,
  error_payload jsonb null,
  attempts integer not null default 0,
  max_attempts integer not null default 3,
  locked_by text null,
  locked_at timestamptz null,
  started_at timestamptz null,
  completed_at timestamptz null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_async_jobs_status_created_at
  on public.async_jobs (status, created_at asc);

create index if not exists idx_async_jobs_user_created_at
  on public.async_jobs (user_id, created_at desc);

create index if not exists idx_async_jobs_request_id
  on public.async_jobs (request_id);

create or replace function public.set_async_jobs_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists trg_async_jobs_updated_at on public.async_jobs;

create trigger trg_async_jobs_updated_at
before update on public.async_jobs
for each row
execute function public.set_async_jobs_updated_at();
