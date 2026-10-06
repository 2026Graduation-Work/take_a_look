import type { Page, Route } from "@playwright/test";

// e2e 서버는 NEXT_PUBLIC_SUPABASE_URL을 이 주소로 띄운다(playwright.config.ts, web-ci.yml).
// 실제 Supabase 없이 브라우저가 부르는 Auth·REST 요청만 가로채 흉내 낸다. 서버 쪽 조회는 연결 실패 → 정적 폴백.
export const SUPABASE_URL = "http://127.0.0.1:54321";

interface MockUser {
  id: string;
  name?: string;
  email: string;
  password: string;
}

function session(user: MockUser) {
  const now = Math.floor(Date.now() / 1000);
  return {
    access_token: `access-${user.id}`,
    refresh_token: `refresh-${user.id}`,
    token_type: "bearer",
    expires_in: 3600,
    expires_at: now + 3600,
    user: authUser(user),
  };
}

function authUser(user: MockUser) {
  return {
    id: user.id,
    aud: "authenticated",
    role: "authenticated",
    email: user.email,
    app_metadata: { provider: "email" },
    user_metadata: user.name ? { full_name: user.name } : {},
    created_at: new Date().toISOString(),
  };
}

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

// 가입·로그인·로그아웃을 흉내 낸다. profile을 주면 서비스 사용자(users)·성향(ips_profiles)이 있는 "준비됨" 상태,
// 없으면 설문 필요 상태. watchlist·stock_notes는 메모리에 담아 upsert·삭제·조회를 흉내 낸다.
export async function mockSupabaseAuth(
  page: Page,
  { profile, notesTableMissing = false }: { profile?: unknown; notesTableMissing?: boolean } = {},
) {
  const users = new Map<string, MockUser>();
  let current: MockUser | null = null;
  const calls: string[] = [];
  const tables: Record<string, Map<string, Record<string, unknown>>> = { watchlist: new Map(), stock_notes: new Map() };

  await page.route(`${SUPABASE_URL}/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    calls.push(`${request.method()} ${url.pathname}`);
    if (url.pathname === "/auth/v1/signup") {
      const { email, password, data } = request.postDataJSON() as { email: string; password: string; data?: { full_name?: string } };
      const user = { id: `user-${users.size + 1}`, email, password, name: data?.full_name };
      users.set(email, user);
      current = user;
      return json(route, session(user));
    }
    if (url.pathname === "/auth/v1/token" && url.searchParams.get("grant_type") === "password") {
      const { email, password } = request.postDataJSON() as { email: string; password: string };
      const user = users.get(email);
      if (!user || user.password !== password) {
        return json(route, { error: "invalid_grant", error_description: "Invalid login credentials" }, 400);
      }
      current = user;
      return json(route, session(user));
    }
    if (url.pathname === "/auth/v1/user") {
      return current ? json(route, authUser(current)) : json(route, { message: "no user" }, 401);
    }
    if (url.pathname === "/auth/v1/logout") {
      current = null;
      return route.fulfill({ status: 204 });
    }
    if (url.pathname.startsWith("/rest/v1/")) {
      const table = url.pathname.slice("/rest/v1/".length);
      const method = request.method();
      if (table === "users" && method === "GET") {
        return json(route, profile && current ? [{ id: `app-${current.id}`, display_name: "테스터" }] : []);
      }
      if (table === "ips_profiles" && method === "GET") return json(route, profile ? [{ profile_payload: profile }] : []);
      // 0006 마이그레이션 적용 전 DB: PostgREST가 모르는 테이블
      if (table === "stock_notes" && notesTableMissing) {
        return json(route, { code: "PGRST205", message: "Could not find the table 'public.stock_notes'" }, 404);
      }
      const rows = tables[table];
      if (rows) {
        const eq = (key: string) => url.searchParams.get(key)?.replace(/^eq\./, "");
        if (method === "GET") {
          const active = eq("is_active");
          return json(route, [...rows.values()].filter((row) => active === undefined || String(row.is_active) === active));
        }
        if (method === "POST") {
          const body = request.postDataJSON() as Record<string, unknown> | Record<string, unknown>[];
          for (const row of Array.isArray(body) ? body : [body]) rows.set(String(row.stock_code), row);
          return route.fulfill({ status: 201 });
        }
        if (method === "DELETE") {
          rows.delete(eq("stock_code") ?? "");
          return route.fulfill({ status: 204 });
        }
      }
      return json(route, method === "GET" ? [] : {});
    }
    return json(route, {});
  });
  return { calls, tables };
}
