"""무료 한도 주간 감시(free-tier-watch.yml). 기준을 넘으면 이슈를 열거나 기존 이슈에 코멘트한다.

기준: docs/ops/free-tier-budget.md. 표준 라이브러리와 gh CLI만 쓴다.
"""

import json
import os
import re
import subprocess
from datetime import date, datetime, timedelta, timezone
from urllib.request import Request, urlopen

DB_LIMIT_MB = 350
STORAGE_LIMIT_MB = 800
NEWSAPI_DAILY_PLAN = 20  # 하루 상한(AGENTS.md 무료 운영 규칙)
PLAN_END = date(2027, 2, 1)
MAX_PUBLISH_LAG = 2  # 영업일(주말만 뺀다. 공휴일이 끼면 하루 늦게 울릴 수 있다)
TITLE = "[ops] 무료 한도 경고"
SITE_URL = "https://takealook-skku.vercel.app"  # Vercel 연동이 덮어쓴 적 있음(docs/auth-setup.md 3-3)
SITE_URL_TITLE = "[ops] 인증 Site URL 변경됨"
OWNER = "Choi-Jung-Hyeon"  # 운영 감시 담당


def weekdays_between(start, end):
    """start 다음 날부터 end까지의 평일 수."""
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


def post_json(url, body, headers):
    request = Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers})
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def site_url():
    """인증 Site URL(Management API). 되돌리지 않고 읽기만 한다."""
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
        # 담당·라벨·Type을 바로 채운다(팀 이슈 규칙). Priority 등 필드는 사람이 정한다
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
    try:
        current = site_url()
    except Exception as exc:  # 측정 실패도 경고로 남긴다
        current = f"읽기 실패({type(exc).__name__})"
    print(json.dumps({"event": "free_tier_watch", **measured, "alerts": alerts, "site_url": current}, ensure_ascii=False))
    if current.rstrip("/") != SITE_URL:
        report(SITE_URL_TITLE, f"{today} 주간 감시\n\n- 인증 Site URL `{current}` ≠ `{SITE_URL}`\n\n"
               "자동으로 되돌리지 않습니다. 확인 후 docs/auth-setup.md 3-3 절차로 되돌려 주세요.")
    if alerts:
        report(TITLE, f"{today} 주간 감시\n\n" + "\n".join(f"- {a}" for a in alerts)
               + f"\n\n측정값: `{json.dumps(measured)}`\n\n기준: docs/ops/free-tier-budget.md")


if __name__ == "__main__":
    main()
