-- 예측 요약 로그(영구 보관)와 차트 배치 보존. 전체 payload 스냅샷은 최근 게시 배치 몇 개만 남기고,
-- 종목·기준일·기간별 클래스 확률·신호만 이 표에 쌓는다(DB 무료 한도, docs/ops/free-tier-budget.md).

create table if not exists public.chart_prediction_log (
  stock_code text not null check (stock_code ~ '^[0-9A-Z]{6}$'),
  as_of date not null,
  horizon integer not null check (horizon in (5, 20)),
  prob_down double precision,
  prob_neutral double precision,
  prob_up double precision,
  signal text check (signal in ('down', 'flat', 'up')), -- 세 확률 중 가장 큰 쪽. 추론 불가면 null
  batch_id text not null,
  created_at timestamptz not null default now(),
  primary key (stock_code, as_of, horizon)
);

alter table public.chart_prediction_log enable row level security;
revoke all on public.chart_prediction_log from anon, authenticated;
grant all on public.chart_prediction_log to service_role;

-- 게시 배치의 스냅샷을 요약 로그에 옮긴다(이미 있으면 건너뜀). 옮긴 행 수를 돌려준다.
create or replace function public.log_chart_predictions()
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  inserted integer;
begin
  insert into public.chart_prediction_log
    (stock_code, as_of, horizon, prob_down, prob_neutral, prob_up, signal, batch_id)
  select s.stock_code, b.as_of, s.horizon, p.down, p.neutral, p.up,
         case when p.down is null then null
              when p.down >= p.neutral and p.down >= p.up then 'down'
              when p.up > p.neutral then 'up'
              else 'flat' end,
         b.id
  from public.chart_signal_snapshots s
  join public.chart_batches b on b.id = s.batch_id and b.status = 'published'
  cross join lateral (
    select (s.payload #>> '{inference,scores,down}')::double precision as down,
           (s.payload #>> '{inference,scores,neutral}')::double precision as neutral,
           (s.payload #>> '{inference,scores,up}')::double precision as up
  ) p
  on conflict (stock_code, as_of, horizon) do nothing;
  get diagnostics inserted = row_count;
  return inserted;
end;
$$;

-- 최근 게시 배치 p_keep개만 남기고, 그보다 오래된 게시·철회·실패 배치를 지운다. staging은 건드리지 않는다.
-- 스냅샷 가드 트리거(0007)는 staging 배치의 스냅샷만 지우게 하므로, 한 트랜잭션 안에서
-- 지울 배치를 staging으로 돌린 뒤 스냅샷 → 배치 순서로 지운다. 먼저 요약 로그에 옮긴다.
create or replace function public.prune_chart_batches(p_keep integer default 5)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  doomed text[];
begin
  if p_keep < 1 then
    raise exception 'p_keep must be at least 1';
  end if;
  perform public.log_chart_predictions();
  select coalesce(array_agg(id), '{}') into doomed
  from public.chart_batches
  where status in ('published', 'withdrawn', 'failed')
    and id not in (
      select id from public.chart_batches
      where status = 'published'
      order by as_of desc
      limit p_keep
    );
  if cardinality(doomed) = 0 then
    return 0;
  end if;
  update public.chart_batches set status = 'staging' where id = any(doomed);
  delete from public.chart_signal_snapshots where batch_id = any(doomed);
  delete from public.chart_batches where id = any(doomed);
  return cardinality(doomed);
end;
$$;

revoke all on function public.log_chart_predictions() from public, anon, authenticated;
revoke all on function public.prune_chart_batches(integer) from public, anon, authenticated;
grant execute on function public.log_chart_predictions() to service_role;
grant execute on function public.prune_chart_batches(integer) to service_role;
