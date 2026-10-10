-- DART 공시 목록(제목·날짜·유형만, 원문 본문은 저장하지 않는다). 하루 전체 공시를 받아 종목 마스터에 맞춘다.
-- 유형 규칙: backend/analysis/text/value_pipeline/disclosures.py, docs/disclosure-kinds.md
create table if not exists public.disclosures (
  rcept_no text primary key check (rcept_no ~ '^[0-9]{14}$'),
  stock_code text not null references public.stocks (code) on delete cascade,
  title text not null check (length(title) between 1 and 300),
  kind text not null,
  filed_on date not null,
  created_at timestamptz not null default now()
);
create index if not exists idx_disclosures_stock_date on public.disclosures (stock_code, filed_on desc);

alter table public.disclosures enable row level security;
drop policy if exists disclosures_public_select on public.disclosures;
create policy disclosures_public_select on public.disclosures for select to anon, authenticated using (true);
revoke all on public.disclosures from anon, authenticated;
grant select on public.disclosures to anon, authenticated;
grant all on public.disclosures to service_role;
