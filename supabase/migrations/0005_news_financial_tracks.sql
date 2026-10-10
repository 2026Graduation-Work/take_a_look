-- Text-analysis persistence for the two-track news pipeline and DART metrics.
-- Browser clients can read these public analysis results. Only a trusted
-- backend using the service role may insert, update, or delete rows.

create table if not exists public.news_sentiment_tracks (
  stock_code text not null references public.stocks (code) on delete cascade,
  track text not null check (track in ('historical', 'live')),
  source text not null check (source in ('bigkinds', 'newsapi_ai')),
  backend text not null,
  status text not null check (
    status in ('ok', 'partial', 'insufficient_data', 'error')
  ),
  as_of timestamptz not null,
  window_start date not null,
  window_end date not null,
  sentiment_mean double precision check (sentiment_mean between -1 and 1),
  sentiment_std double precision check (sentiment_std >= 0),
  article_count integer not null default 0 check (article_count >= 0),
  publisher_count integer not null default 0 check (publisher_count >= 0),
  fetched_count integer not null default 0 check (fetched_count >= 0),
  relevant_count integer not null default 0 check (relevant_count >= 0),
  newest_published_at timestamptz,
  lag_minutes integer check (lag_minutes >= 0),
  provider_total_results bigint check (provider_total_results >= 0),
  provider_returned_count integer check (provider_returned_count >= 0),
  provider_pages integer check (provider_pages >= 0),
  provider_truncated boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (stock_code, track),
  constraint news_sentiment_tracks_window_valid check (
    window_start <= window_end
  ),
  constraint news_sentiment_tracks_source_matches_track check (
    (track = 'historical' and source = 'bigkinds')
    or (track = 'live' and source = 'newsapi_ai')
  )
);

create table if not exists public.news_sentiment_daily (
  stock_code text not null,
  track text not null check (track in ('historical', 'live')),
  sentiment_date date not null,
  status text not null check (status in ('ok', 'insufficient_data')),
  sentiment_mean double precision check (sentiment_mean between -1 and 1),
  sentiment_std double precision check (sentiment_std >= 0),
  article_count integer not null default 0 check (article_count >= 0),
  publisher_count integer not null default 0 check (publisher_count >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (stock_code, track, sentiment_date),
  foreign key (stock_code, track)
    references public.news_sentiment_tracks (stock_code, track)
    on delete cascade
);

create table if not exists public.news_articles (
  stock_code text not null,
  track text not null check (track in ('historical', 'live')),
  news_id text not null,
  title text not null,
  press text not null default '',
  url text not null default '',
  article_date date not null,
  published_at timestamptz,
  event_id text not null default '',
  sentiment_score double precision not null check (
    sentiment_score between -1 and 1
  ),
  last_seen_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (stock_code, track, news_id),
  foreign key (stock_code, track)
    references public.news_sentiment_tracks (stock_code, track)
    on delete cascade
);

create table if not exists public.financial_snapshots (
  id uuid primary key default gen_random_uuid(),
  stock_code text not null references public.stocks (code) on delete cascade,
  as_of date not null,
  fiscal_year integer not null check (fiscal_year >= 1900),
  source text not null default 'dart' check (source = 'dart'),
  status text not null check (status in ('ok', 'partial', 'invalid')),
  statement text not null check (statement in ('CFS', 'OFS')),
  receipt_no text not null,
  filed_at date not null,
  shares_basis text not null,
  price double precision check (price >= 0),
  price_as_of date,
  price_source text,
  validation_errors jsonb not null default '[]'::jsonb check (
    jsonb_typeof(validation_errors) = 'array'
  ),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (stock_code, as_of, fiscal_year),
  constraint financial_snapshots_filing_not_future check (filed_at <= as_of),
  constraint financial_snapshots_price_pair check (
    (price is null and price_as_of is null and price_source is null)
    or (price is not null and price_as_of is not null and price_source is not null)
  )
);

create table if not exists public.financial_metrics (
  snapshot_id uuid not null references public.financial_snapshots (id)
    on delete cascade,
  metric_key text not null check (
    metric_key in (
      'per',
      'pbr',
      'roe',
      'operating_margin',
      'debt_ratio',
      'revenue_growth'
    )
  ),
  value double precision,
  unit text not null check (unit in ('multiple', 'percent')),
  basis text not null,
  note text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (snapshot_id, metric_key)
);

create index if not exists idx_news_sentiment_daily_stock_date
  on public.news_sentiment_daily (stock_code, track, sentiment_date desc);
create index if not exists idx_news_articles_stock_date
  on public.news_articles (stock_code, track, article_date desc);
create index if not exists idx_financial_snapshots_stock_date
  on public.financial_snapshots (stock_code, as_of desc);

alter table public.news_sentiment_tracks enable row level security;
alter table public.news_sentiment_daily enable row level security;
alter table public.news_articles enable row level security;
alter table public.financial_snapshots enable row level security;
alter table public.financial_metrics enable row level security;

drop policy if exists news_sentiment_tracks_public_select
  on public.news_sentiment_tracks;
create policy news_sentiment_tracks_public_select
  on public.news_sentiment_tracks
  for select to anon, authenticated using (true);

drop policy if exists news_sentiment_daily_public_select
  on public.news_sentiment_daily;
create policy news_sentiment_daily_public_select
  on public.news_sentiment_daily
  for select to anon, authenticated using (true);

drop policy if exists news_articles_public_select on public.news_articles;
create policy news_articles_public_select
  on public.news_articles
  for select to anon, authenticated using (true);

drop policy if exists financial_snapshots_public_select
  on public.financial_snapshots;
create policy financial_snapshots_public_select
  on public.financial_snapshots
  for select to anon, authenticated using (true);

drop policy if exists financial_metrics_public_select
  on public.financial_metrics;
create policy financial_metrics_public_select
  on public.financial_metrics
  for select to anon, authenticated using (true);

grant usage on schema public to anon, authenticated;

revoke all on table
  public.news_sentiment_tracks,
  public.news_sentiment_daily,
  public.news_articles,
  public.financial_snapshots,
  public.financial_metrics
from anon, authenticated;

grant select on table
  public.news_sentiment_tracks,
  public.news_sentiment_daily,
  public.news_articles,
  public.financial_snapshots,
  public.financial_metrics
to anon, authenticated;
