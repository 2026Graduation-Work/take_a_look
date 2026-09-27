-- Daily raw inputs and private feature artifacts for the v2 chart detail.
do $$
declare name text;
begin
  for name in select conname from pg_constraint
    where conrelid = 'public.chart_releases'::regclass
      and contype = 'c' and pg_get_constraintdef(oid) like '%same_stock_up_down_001_sigma_rel010_v1%'
  loop
    execute format('alter table public.chart_releases drop constraint %I', name);
  end loop;
  for name in select conname from pg_constraint
    where conrelid = 'public.chart_signal_snapshots'::regclass
      and contype = 'c' and pg_get_constraintdef(oid) like '%chart_signal_detail_v1%'
  loop
    execute format('alter table public.chart_signal_snapshots drop constraint %I', name);
  end loop;
end;
$$;
alter table public.chart_releases add constraint chart_releases_policy_id_check
  check (policy_id in ('same_stock_up_down_001_sigma_rel010_v1',
                      'multi_stock_up_sigma_001_005_v1'));

alter table public.chart_signal_snapshots add constraint chart_signal_snapshots_payload_check
  check (payload->>'contract' in ('chart_signal_detail_v1', 'chart_signal_detail_v2'));

alter table public.chart_batches add column pack_id text;

create table public.chart_universe (
  as_of date not null,
  stock_code text not null check (stock_code ~ '^[0-9A-Z]{6}$'),
  stock_name text not null check (length(stock_name) > 0),
  primary key (as_of, stock_code)
);

create table public.chart_prices (
  stock_code text not null check (stock_code ~ '^[0-9A-Z]{6}$'),
  trade_date date not null,
  open double precision,
  high double precision,
  low double precision,
  close double precision check (close is null or close > 0),
  volume double precision check (volume is null or volume >= 0),
  vwap double precision,
  change_percent double precision,
  raw_close double precision,
  raw_volume double precision,
  amount double precision,
  adjustment_factor double precision,
  updated_at timestamptz not null default now(),
  primary key (stock_code, trade_date)
);
create index chart_prices_date_idx on public.chart_prices (trade_date);

create table public.chart_feature_snapshots (
  stock_code text not null check (stock_code ~ '^[0-9A-Z]{6}$'),
  as_of date not null,
  builder_id text not null,
  input_sha256 text not null check (input_sha256 ~ '^[0-9a-f]{64}$'),
  feature_sha256 text not null check (feature_sha256 ~ '^[0-9a-f]{64}$'),
  storage_path text not null,
  created_at timestamptz not null default now(),
  primary key (stock_code, as_of, builder_id, input_sha256)
);

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('chart-features', 'chart-features', false, 52428800,
        array['application/octet-stream'])
on conflict (id) do update set public = false;

alter table public.chart_universe enable row level security;
alter table public.chart_prices enable row level security;
alter table public.chart_feature_snapshots enable row level security;
revoke all on public.chart_universe, public.chart_prices, public.chart_feature_snapshots
  from anon, authenticated;
grant all on public.chart_universe, public.chart_prices, public.chart_feature_snapshots
  to service_role;
