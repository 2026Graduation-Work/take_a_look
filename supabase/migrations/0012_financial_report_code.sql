-- 재무 스냅샷의 정기보고서 종류(DART reprt_code). 화면에 "2026년 반기 기준"처럼 보고서 시점을 보인다.
-- 11013 1분기 · 11012 반기 · 11014 3분기 · 11011 사업보고서. 예전 행(null)은 사업보고서로 본다.
alter table public.financial_snapshots
  add column if not exists report_code text check (report_code in ('11013', '11012', '11014', '11011'));
