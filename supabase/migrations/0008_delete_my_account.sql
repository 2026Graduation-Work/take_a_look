-- 본인 계정 삭제. auth.users 행을 지우면 public.users를 거쳐 성향·보유·관심 종목·판단 메모가
-- on delete cascade(0001, 0006)로 함께 지워진다. 호출한 사람 자신의 행만 지운다.
create or replace function public.delete_my_account()
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  if auth.uid() is null then
    raise exception 'not authenticated';
  end if;
  delete from auth.users where id = auth.uid();
end;
$$;

revoke all on function public.delete_my_account() from public, anon;
grant execute on function public.delete_my_account() to authenticated;
