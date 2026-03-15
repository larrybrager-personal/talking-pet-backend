-- Weighted credit tracking for talking-pet generations.
-- Narrow additive migration: preserves existing pet_videos rows and falls back cleanly.

alter table if exists public.pet_videos
  add column if not exists credit_cost integer;

alter table if exists public.pet_videos
  add column if not exists plan_tier text;

alter table if exists public.pet_videos
  add column if not exists routing_quality text;

update public.pet_videos
set credit_cost = case
  when model in ('bytedance/seedance-1-pro-fast', 'wan-video/wan-2.2-5b-fast', 'wan-video/wan-2.2-i2v-fast', 'minimax/hailuo-2.3-fast', 'minimax/hailuo-02-fast') then 1
  when model in ('wan-video/wan2.6-i2v-flash', 'kwaivgi/kling-v2.5-turbo-pro', 'wan-video/wan-2.5-i2v-fast') then 2
  when model in ('wan-video/wan-2.6-i2v', 'pixverse/pixverse-v4', 'wan-video/wan-2.2-s2v', 'veed/fabric-1.0') then 4
  when model in ('kwaivgi/kling-v2.6', 'minimax/hailuo-2.3', 'wan-video/wan-2.2-i2v-a14b', 'wan-video/wan-2.5-i2v', 'google/veo-3.1-fast', 'bytedance/seedance-1-pro') then 8
  else coalesce(credit_cost, 1)
end
where credit_cost is null;

create index if not exists idx_pet_videos_user_created_credit_cost
  on public.pet_videos (user_id, created_at desc, credit_cost);
