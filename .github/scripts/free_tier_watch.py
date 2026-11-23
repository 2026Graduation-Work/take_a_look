import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from urllib.request import Request, urlopen

DB_LIMIT_MB = 350
STORAGE_LIMIT_MB = 700  # 무료 한도 1GB에 여유를 둔 값
NEWSAPI_DAILY_PLAN = 20
PLAN_END = date(2027, 2, 1)
MAX_PUBLISH_LAG = 2  # 주말만 뺀 영업일. 공휴일은 세지 않는다
TITLE = "[ops] 무료 한도 경고"
SITE_URL = "https://takealook-skku.vercel.app"  # Vercel 연동이 이 값을 덮어쓸 수 있다
SITE_URL_TITLE = "[ops] 인증 Site URL 변경됨"
OWNER = "Choi-Jung-Hyeon"
SECURITY_TITLE = "[ops] 보안 감시 경고"
SIGNUPS_7D_LIMIT = 50  # 수업 과제 규모에서 주 50건을 넘는 가입은 남용 의심


def weekdays_between(start, end):
    return sum((start + timedelta(days=i)).weekday() < 5 for i in range(1, (end - start).days + 1))


def check(usage, newsapi_remaining, today):
    alerts = []
    db_mb, storage_mb = usage["db_bytes"] / 2**20, usage["storage_bytes"] / 2**20
    if db_mb > DB_LIMIT_MB:
        alerts.append(f"DB {db_mb:.0f}MB > {DB_LIMIT_MB}MB")
    if storage_mb > STORAGE_LIMIT_MB:
        alerts.append(f"Storage {storage_mb:.0f}MB > {STORAGE_LIMIT_MB}MB")
    needed = NEWSAPI_DAILY_PLAN * weekdays_between(today, PLAN_END)
    if newsapi_remaining is None or newsapi_remaining < needed:
        alerts.append(f"NewsAPI.ai 남은 횟수 {newsapi_remaining} < 2/1까지 계획 {needed}")
    as_of = usage.get("last_published_as_of")
    lag = weekdays_between(date.fromisoformat(as_of), today) if as_of else None
    if lag is None or lag > MAX_PUBLISH_LAG:
        alerts.append(f"차트 게시가 {lag}영업일 밀림(마지막 {as_of})")
    return alerts, {"db_mb": round(db_mb), "storage_mb": round(storage_mb),
                    "newsapi_remaining": newsapi_remaining, "last_published_as_of": as_of}


def security_check(usage):
    alerts = []
    tables = usage.get("rls_disabled_tables")
    if tables is None:
        alerts.append("RLS 검사값이 없음(마이그레이션 0015 확인)")
    elif tables:
        alerts.append(f"RLS가 꺼진 public 테이블 {len(tables)}개: {', '.join(tables)}")
    if (usage.get("signups_7d") or 0) > SIGNUPS_7D_LIMIT:
        alerts.append(f"최근 7일 가입 {usage['signups_7d']}건 > {SIGNUPS_7D_LIMIT}건")
    return alerts


def post_json(url, body, headers):
    request = Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers})
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def site_url():
    ref = re.match(r"https://([^.]+)\.", os.environ["SUPABASE_URL"]).group(1)
    request = Request(f"https://api.supabase.com/v1/projects/{ref}/config/auth",
                      headers={"Authorization": "Bearer " + os.environ["SUPABASE_ACCESS_TOKEN"],
                               "User-Agent": "free-tier-watch"})  # 기본 urllib UA는 Cloudflare가 막을 수 있다
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read())["site_url"]


def report(title, body):
    found = subprocess.run(["gh", "issue", "list", "--state", "open", "--search", f'"{title}" in:title',
                            "--json", "number", "-q", ".[0].number"], capture_output=True, text=True, check=True).stdout.strip()
    if found:
        subprocess.run(["gh", "issue", "comment", found, "--body", body], check=True)
    else:
        url = subprocess.run(["gh", "issue", "create", "--title", title, "--body", body, "--label", "bug",
                              "--assignee", OWNER], capture_output=True, text=True, check=True).stdout.strip()
        subprocess.run(["gh", "api", "-X", "PATCH", f"repos/{os.environ['GH_REPO']}/issues/{url.rsplit('/', 1)[1]}",
                        "-f", "type=Bug"], check=False)


def main():
    key = os.environ["SUPABASE_SECRET_KEY"]
    usage = post_json(os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/rpc/budget_usage", {}, {"apikey": key})
    try:
        newsapi = post_json("https://eventregistry.org/api/v1/usage", {"apiKey": os.environ["NEWSAPI_AI_KEY"]}, {})
        remaining = newsapi["availableTokens"] - newsapi["usedTokens"]
    except Exception:  # 측정 실패도 경고로 남긴다
        remaining = None
    today = datetime.now(timezone(timedelta(hours=9))).date()
    alerts, measured = check(usage, remaining, today)
    security = security_check(usage)
    measured.update(signups_24h=usage.get("signups_24h"), signups_7d=usage.get("signups_7d"),
                    rls_disabled_tables=usage.get("rls_disabled_tables"))
    try:
        current = site_url()
    except Exception as exc:  # 측정 실패도 경고로 남긴다
        current = f"읽기 실패({type(exc).__name__})"
    print(json.dumps({"event": "free_tier_watch", **measured, "alerts": alerts + security, "site_url": current},
                     ensure_ascii=False))
    if os.environ.get("DRY_RUN") == "true":
        sys.exit(1 if security else 0)
    if current.rstrip("/") != SITE_URL:
        report(SITE_URL_TITLE, f"{today} 주간 감시\n\n- 인증 Site URL `{current}` ≠ `{SITE_URL}`\n\n"
               "자동으로 되돌리지 않습니다. 확인 후 docs/auth-setup.md 3-3 절차로 되돌려 주세요.")
    if alerts:
        report(TITLE, f"{today} 주간 감시\n\n" + "\n".join(f"- {a}" for a in alerts)
               + f"\n\n측정값: `{json.dumps(measured)}`\n\n기준: docs/ops/free-tier-budget.md")
    if security:
        report(SECURITY_TITLE, f"{today} 주간 감시\n\n" + "\n".join(f"- {a}" for a in security)
               + "\n\n점검 기준: docs/security/2026-10-audit.md")
        sys.exit(1)  # 작업을 실패로 표시해 Actions 알림 메일도 가게 한다


if __name__ == "__main__":
    main()
