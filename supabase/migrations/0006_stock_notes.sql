-- 종목 상세의 "내 판단 메모". 사용자별·종목별 한 줄(마지막 메모만 둔다). 본인 행만 읽고 쓴다.
-- 적용 전에는 프론트(lib/stock-marks.ts)가 이 브라우저에만 저장한다.

create table if not exists public.stock_notes (
  user_id text not null references public.users (id) on delete cascade,
  stock_code text not null,
  note text not null check (char_length(note) between 1 and 1000),
  updated_at timestamptz not null default now(),
  primary key (user_id, stock_code)
);

alter table public.stock_notes enable row level security;

drop policy if exists stock_notes_owner_all on public.stock_notes;
create policy stock_notes_owner_all on public.stock_notes
  for all to authenticated
  using (
    exists (
      select 1 from public.users as app_user
      where app_user.id = stock_notes.user_id
        and app_user.auth_user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from public.users as app_user
      where app_user.id = stock_notes.user_id
        and app_user.auth_user_id = auth.uid()
    )
  );

revoke all on table public.stock_notes from anon, authenticated;
grant select, insert, update, delete on table public.stock_notes to authenticated;
