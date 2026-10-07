-- 종목 마스터의 1년 변동성과 시장 안 백분위(stock_master.py가 매일 계산, 위험 등급과 같은 계산).
-- 화면의 "가격 흔들림" 백분위·체크포인트 판정에 쓴다. risk_as_of = 계산 기준일(universe as_of).
alter table public.stocks
  add column if not exists volatility_annual double precision check (volatility_annual is null or volatility_annual >= 0),
  add column if not exists volatility_percentile double precision check (volatility_percentile is null or volatility_percentile between 0 and 1),
  add column if not exists risk_as_of date;
