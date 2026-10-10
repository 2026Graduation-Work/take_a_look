-- Additive H5/H20 detail contract; the legacy predictions schema is unchanged.
create table public.chart_releases (
  id text primary key,
  horizon integer not null check (horizon in (5, 20)),
  profile text not null check ((horizon = 5 and profile = 'aggressive') or
                                (horizon = 20 and profile = 'stable')),
  policy_id text not null check (policy_id = 'same_stock_up_down_001_sigma_rel010_v1'),
  model_sha256 text not null check (model_sha256 ~ '^[0-9a-f]{64}$'),
  features_sha256 text not null check (features_sha256 ~ '^[0-9a-f]{64}$'),
  cases_sha256 text not null check (cases_sha256 ~ '^[0-9a-f]{64}$'),
  config_sha256 text not null check (config_sha256 ~ '^[0-9a-f]{64}$'),
  manifest jsonb not null check (jsonb_typeof(manifest) = 'object'),
  created_at timestamptz not null default now()
);

create table public.chart_batches (
  id text primary key,
  as_of date not null,
  release_h5 text not null references public.chart_releases(id),
  release_h20 text not null references public.chart_releases(id),
  expected_stock_codes text[] not null check (cardinality(expected_stock_codes) > 0),
  status text not null default 'staging' check (status in ('staging', 'published', 'failed', 'withdrawn')),
  result jsonb not null default '{}'::jsonb check (jsonb_typeof(result) = 'object'),
  created_at timestamptz not null default now(),
  published_at timestamptz,
  check (release_h5 <> release_h20),
  check (array_position(expected_stock_codes, null) is null)
);

create unique index chart_batches_one_published_per_day
  on public.chart_batches (as_of) where status = 'published';

create table public.chart_signal_snapshots (
  batch_id text not null references public.chart_batches(id) on delete cascade,
  stock_code text not null check (stock_code ~ '^[0-9A-Z]{6}$'),
  horizon integer not null check (horizon in (5, 20)),
  payload jsonb not null,
  payload_sha256 text not null check (payload_sha256 ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default now(),
  primary key (batch_id, stock_code, horizon),
  check (payload->>'contract' is not distinct from 'chart_signal_detail_v1'),
  check (payload->>'stock_code' is not distinct from stock_code),
  check (nullif(payload->>'stock_name', '') is not null),
  check ((payload->>'horizon')::integer is not distinct from horizon),
  check (payload->>'batch_id' is not distinct from batch_id)
);

-- A snapshot write holds the parent row until commit. Publication takes the
-- same lock, so the completeness check and status change cannot race uploads.
create function public.guard_chart_snapshot_stage()
returns trigger language plpgsql security definer set search_path = '' as $$
declare
  parent_status text;
  target_batch_id text;
begin
  if tg_op = 'DELETE' then
    target_batch_id := old.batch_id;
  else
    target_batch_id := new.batch_id;
    if tg_op = 'UPDATE' and old.batch_id is distinct from target_batch_id then
      raise exception 'Moving a chart snapshot between batches is forbidden';
    end if;
  end if;
  select status into parent_status from public.chart_batches
  where id = target_batch_id for update;
  if parent_status is distinct from 'staging' then
    raise exception 'Chart snapshots are writable only in a staging batch';
  end if;
  if tg_op = 'DELETE' then return old; end if;
  return new;
end;
$$;
create trigger chart_snapshot_stage_guard before insert or update or delete
  on public.chart_signal_snapshots for each row
  execute function public.guard_chart_snapshot_stage();

alter table public.chart_releases enable row level security;
alter table public.chart_batches enable row level security;
alter table public.chart_signal_snapshots enable row level security;

create policy chart_batches_published_read on public.chart_batches for select
  to anon, authenticated using (status = 'published');
create policy chart_snapshots_published_read on public.chart_signal_snapshots for select
  to anon, authenticated using (exists (
    select 1 from public.chart_batches b where b.id = chart_signal_snapshots.batch_id and b.status = 'published'
  ));
create policy chart_releases_published_read on public.chart_releases for select
  to anon, authenticated using (exists (
    select 1 from public.chart_batches b where b.status = 'published'
      and (b.release_h5 = chart_releases.id or b.release_h20 = chart_releases.id)
  ));

revoke all on public.chart_releases, public.chart_batches, public.chart_signal_snapshots
  from anon, authenticated;
grant select on public.chart_releases, public.chart_batches, public.chart_signal_snapshots
  to anon, authenticated;
grant all on public.chart_releases, public.chart_batches, public.chart_signal_snapshots
  to service_role;

create function public.publish_chart_batch(p_batch_id text)
returns void language plpgsql security definer set search_path = '' as $$
declare
  batch public.chart_batches%rowtype;
  expected_count integer;
  actual_count integer;
begin
  select * into batch from public.chart_batches where id = p_batch_id for update;
  if not found or batch.status <> 'staging' then
    raise exception 'Chart batch is absent or not staging';
  end if;
  if (select horizon from public.chart_releases where id = batch.release_h5) is distinct from 5 or
     (select horizon from public.chart_releases where id = batch.release_h20) is distinct from 20 then
    raise exception 'Wrong H5/H20 release combination';
  end if;
  if cardinality(batch.expected_stock_codes) <> (
    select count(distinct code) from unnest(batch.expected_stock_codes) as code
  ) then
    raise exception 'Duplicate expected stock codes';
  end if;
  expected_count := 2 * cardinality(batch.expected_stock_codes);
  select count(*) into actual_count from public.chart_signal_snapshots s
  where s.batch_id = p_batch_id and s.stock_code = any(batch.expected_stock_codes)
    and s.payload->>'data_asof' = batch.as_of::text
    and s.payload->>'release_id' = case when s.horizon = 5 then batch.release_h5 else batch.release_h20 end;
  if actual_count <> expected_count or
     (select count(*) from public.chart_signal_snapshots where batch_id = p_batch_id) <> expected_count then
    raise exception 'Incomplete chart snapshots: % of %', actual_count, expected_count;
  end if;
  -- A corrected run for the same date replaces its predecessor in this
  -- transaction only after the new batch has passed every completeness check.
  update public.chart_batches set status = 'withdrawn'
  where as_of = batch.as_of and status = 'published' and id <> p_batch_id;
  update public.chart_batches set status = 'published', published_at = now()
  where id = p_batch_id;
end;
$$;

create function public.withdraw_chart_batch(p_batch_id text)
returns void language plpgsql security definer set search_path = '' as $$
begin
  update public.chart_batches set status = 'withdrawn'
  where id = p_batch_id and status = 'published';
  if not found then raise exception 'Published chart batch not found'; end if;
end;
$$;

revoke all on function public.guard_chart_snapshot_stage(),
  public.publish_chart_batch(text), public.withdraw_chart_batch(text)
  from public, anon, authenticated;
grant execute on function public.publish_chart_batch(text), public.withdraw_chart_batch(text)
  to service_role;

create view public.latest_chart_signal_snapshots with (security_invoker = true) as
select s.batch_id, s.stock_code, s.horizon, s.payload, s.payload_sha256
from public.chart_signal_snapshots s
join (
  select id from public.chart_batches where status = 'published'
  order by as_of desc, published_at desc, id desc limit 1
) b on b.id = s.batch_id;
grant select on public.latest_chart_signal_snapshots to anon, authenticated;
