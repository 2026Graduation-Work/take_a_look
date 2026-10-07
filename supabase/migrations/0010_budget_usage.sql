-- 무료 한도 감시용 읽기 함수(주 1회 워크플로 free-tier-watch.yml). DB·Storage 크기와 마지막 게시 기준일.
create or replace function public.budget_usage()
returns jsonb
language sql
security definer
set search_path = ''
stable
as $$
  select jsonb_build_object(
    'db_bytes', pg_catalog.pg_database_size(pg_catalog.current_database()),
    'storage_bytes', (select coalesce(sum((metadata->>'size')::bigint), 0) from storage.objects),
    'last_published_as_of', (select max(as_of) from public.chart_batches where status = 'published')
  );
$$;

revoke all on function public.budget_usage() from public, anon, authenticated;
grant execute on function public.budget_usage() to service_role;
