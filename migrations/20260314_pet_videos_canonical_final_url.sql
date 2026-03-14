-- Canonical playback URL alignment for pet_videos.
-- final_url is the frontend playback artifact. provider_video_url stores raw provider output.

alter table if exists public.pet_videos
  add column if not exists final_url text;

alter table if exists public.pet_videos
  add column if not exists provider_video_url text;

update public.pet_videos
set final_url = coalesce(final_url, video_url)
where final_url is null;

update public.pet_videos
set video_url = coalesce(video_url, final_url)
where video_url is null;

create index if not exists idx_pet_videos_final_url
  on public.pet_videos (final_url);
