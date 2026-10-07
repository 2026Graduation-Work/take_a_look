-- 투자자별 순매수(주). KRX 시장 전체를 영업일마다 한 번에 받는다(pykrx, 개인·외국인·기관합계 3회).
-- 최근 60영업일만 남긴다(backend/analysis/chart/supply.py). 공개 읽기.
create table if not exists public.supply_demand (
  stock_code text not null references public.stocks (code) on delete cascade,
  trade_date date not null,
  retail bigint not null,
  foreign_investor bigint not null,
  institution bigint not null,
  created_at timestamptz not null default now(),
  primary key (stock_code, trade_date)
);
create index if not exists idx_supply_demand_date on public.supply_demand (trade_date);

alter table public.supply_demand enable row level security;
drop policy if exists supply_demand_public_select on public.supply_demand;
create policy supply_demand_public_select on public.supply_demand for select to anon, authenticated using (true);
revoke all on public.supply_demand from anon, authenticated;
grant select on public.supply_demand to anon, authenticated;
grant all on public.supply_demand to service_role;
