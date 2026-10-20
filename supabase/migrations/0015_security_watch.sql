-- 보안 감시(docs/security/2026-10-audit.md). 주간 감시(free-tier-watch.yml)가 읽는 budget_usage()에 두 값을 더한다.
-- - rls_disabled_tables: RLS가 꺼진 public 테이블 이름. 0개가 아니면 감시 작업이 실패한다
-- - signups_24h, signups_7d: 새 가입 수(이메일 확인이 꺼져 있어 가입 남용을 숫자로 본다)
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
    'last_published_as_of', (select max(as_of) from public.chart_batches where status = 'published'),
    'rls_disabled_tables', (
      select coalesce(jsonb_agg(c.relname order by c.relname), '[]'::jsonb)
      from pg_catalog.pg_class c join pg_catalog.pg_namespace n on n.oid = c.relnamespace
      where n.nspname = 'public' and c.relkind in ('r', 'p') and not c.relrowsecurity
    ),
    'signups_24h', (select count(*) from auth.users where created_at > now() - interval '1 day'),
    'signups_7d', (select count(*) from auth.users where created_at > now() - interval '7 days')
  );
$$;

revoke all on function public.budget_usage() from public, anon, authenticated;
grant execute on function public.budget_usage() to service_role;

-- 최신 게시 신호 뷰는 읽기 전용이다. Supabase 기본 권한으로 붙은 쓰기 권한(INSERT, UPDATE, DELETE, TRUNCATE 등)을 거둔다.
-- security_invoker 뷰라 아래 테이블 RLS가 이미 막고 있지만, 권한 표에서도 읽기만 남긴다.
revoke all on public.latest_chart_signal_snapshots from anon, authenticated;
grant select on public.latest_chart_signal_snapshots to anon, authenticated;
