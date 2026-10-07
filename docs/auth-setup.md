# 계정 로그인 설정 체크리스트 (사람이 하는 일)

코드는 준비돼 있고(CC-4), 아래 설정은 Supabase·Vercel 콘솔에서 사람이 합니다.
**Preview에서 먼저 확인하고, 문제가 없을 때 Production에 적용합니다.**

- 데모 계정("데모 계정으로 둘러보기")은 환경변수와 관계없이 항상 동작합니다. 설정 도중에도 교수님·심사자는 데모로 둘러볼 수 있습니다.
- 환경변수가 없으면 로그인 화면의 "이메일로 시작"은 "계정 기능이 아직 연결되지 않았어요" 안내만 보입니다.

## 현재 상태 (2026-10-07)

공개 주소: **https://takealook-skku.vercel.app** (기존 주소 https://stock-prediction-v2-chi.vercel.app 도 동작, Vercel 로그인 없이 열림)

| 항목 | 상태 |
|---|---|
| 마이그레이션 0001~0014 · seed.sql | ✅ 적용 완료. `supabase migration list`에서 로컬·원격 일치(2026-10-07) (Supabase 'Take a Look', ref `oaqksneegnpteextxgux`, 서울) |
| RLS | ✅ anon 키로 확인: 종목·시장 상태는 읽힘, 개인 테이블은 42501로 거부 |
| Vercel 환경변수(4번) | ✅ Production·Preview 등록 + 프로덕션 재배포 완료. 로그인 화면에 이메일 입력칸이 보임 |
| Auth URL 설정(3-3) | ✅ 2026-09-22 콘솔에서 입력(Site URL + Redirect 3줄), API로 확인 |
| Confirm email(3-2) | ✅ 2026-09-22 꺼짐(`mailer_autoconfirm=true`) |
| 프로덕션 확인 | ✅ 2026-09-22 Playwright: 가입 → 16문항 → 저장 → 보유 종목 → 대시보드 → 로그아웃 → 재로그인(설문 없이 대시보드, 결과 유지) → 데모 버튼. 테스트 계정은 삭제 |

> ⚠️ **교수님 검토 기간(9/28~10/2) 전에 접속 확인.** Supabase 무료 플랜은 7일간 요청이 없으면 프로젝트를
> 일시정지합니다. 9/27 전후로 공개 주소에서 로그인을 한 번 해 보고, 멈춰 있으면 Supabase 대시보드에서
> Restore를 누릅니다(데모 계정은 Supabase 없이도 동작).

## 0. 준비물

- Supabase 프로젝트 (Dashboard 접근 권한)
- Vercel 프로젝트 `take-a-look` (Settings 접근 권한)
- 이 저장소의 `supabase/migrations/*.sql`, `supabase/seed.sql`

## 1. Supabase — 마이그레이션 (CLI 기본, SQL Editor 대안)

2026-10-07부터 0009 이후는 CLI(`supabase db push`)로 적용합니다. 운영에 바로 들어가니 **팀에 적용 여부를 먼저 물어보고** 실행하세요. SQL Editor로 적용했다면 `migration repair`로 기록만 맞춥니다(아래 CLI 절차).

| 파일 | 하는 일 | 필수 |
|---|---|---|
| `0001_init.sql` | 테이블 9개, RLS 정책, 권한 | 필수 |
| `0002_market_index_quotes.sql` | `market_status.index_quotes` 컬럼 | 필수 |
| `0003_ips_profiles_schema_v11.sql` | `ips_profiles.schema_version`에 `1.1.0` 허용 | **필수** — 새 설문은 항상 `1.1.0`으로 저장하므로, 없으면 설문 저장이 실패합니다 |
| `0004_holdings_avg_price_nullable.sql` | 평균 매입가 비워 두기 허용 | 필수 |
| `0005_news_financial_tracks.sql` | 뉴스 감성·재무 트랙 테이블 | 필수 |
| `0006_stock_notes.sql` | 판단 메모 | 필수 |
| `0007_chart_signal_detail_v2.sql` | 차트 배치·스냅샷·가격·종목 목록 | 필수 |
| `0008_delete_my_account.sql` | 본인 계정 삭제 함수 | 필수 |
| `0009_chart_prediction_log.sql` | 예측 요약 로그(영구) + 게시 배치 보존 함수 | 필수 |
| `0010_budget_usage.sql` | 무료 한도 감시용 크기 조회 함수 | 필수 |
| `0011_disclosures.sql` | DART 공시 목록(제목·날짜·유형) | 필수 |
| `0012_financial_report_code.sql` | 재무 스냅샷의 정기보고서 종류 | 필수 |
| `0013_supply_demand.sql` | 투자자별 순매수(60영업일) | 필수 |
| `0014_stock_volatility.sql` | 종목 마스터 1년 변동성·백분위 | 필수 |

CLI로 확인하기 (2026-10-07에 0001~0008 기록을 맞춘 뒤, 0009~0014는 CLI로 적용):

1. 루트 `.env`에 `SUPABASE_DB_PASSWORD`·`SUPABASE_ACCESS_TOKEN`을 넣고 `set -a; . ./.env; set +a`로 불러옵니다(값을 명령에 직접 쓰지 않음).
2. 처음 한 번 `supabase link --project-ref oaqksneegnpteextxgux` (프로젝트 "Take a Look").
3. `supabase migration list` — Local·Remote 열이 같으면 적용 기록이 맞습니다.
4. SQL Editor로 새 파일을 적용했다면 `supabase migration repair --status applied <버전>`으로 기록만 맞춥니다.
5. `supabase db push`는 운영에 바로 적용되므로 팀에 먼저 묻고 실행합니다.

적용 여부 확인 쿼리:

```sql
-- 1이 나오면 0001 적용됨
select count(*) from information_schema.tables where table_schema = 'public' and table_name = 'ips_profiles';
-- index_quotes가 나오면 0002 적용됨
select column_name from information_schema.columns where table_name = 'market_status' and column_name = 'index_quotes';
-- 결과에 '1.1.0'이 들어 있으면 0003 적용됨
select pg_get_constraintdef(oid) from pg_constraint where conname = 'ips_profiles_schema_version_check';
```

## 2. Supabase — 시드 데이터 (선택)

`seed.sql`은 종목 5개, 예측 4행(모두 `stable` 모델), 시장 상태 1행, 김민지 데모 사용자 행을 넣습니다.

| seed 적용 | 실제 계정 화면 |
|---|---|
| 안 함 | 대시보드: "오늘 보여 줄 종목 신호가 아직 없어요" 안내 + 시장 브리핑은 예시값. 종목 상세: "실제 상세 데이터를 불러오지 못해 샘플 데이터를 표시합니다" 안내 후 예시 화면 |
| 함 | 대시보드에 종목 카드가 보임(단, `stable` 성향만). `aggressive`로 진단된 계정은 예측 행이 없어 위와 같은 빈 안내가 나옵니다 |

어느 쪽이든 화면이 깨지지는 않습니다. 시연에서 종목 카드를 보여 주려면 seed를 적용하세요.

## 3. Supabase — Authentication 설정

Authentication 메뉴에서:

1. **Providers → Email**: 켜져 있는지 확인합니다.
2. **이메일 확인(Confirm email)**:
   - 끄면: 비밀번호로 가입하자마자 로그인됩니다. **발표·시연 기간에는 끄는 것을 권장합니다.** 무료 플랜의 메일 발송 한도(시간당 몇 통)에 막히지 않습니다.
   - 켜면: 가입 후 확인 메일의 링크를 눌러야 로그인됩니다. 화면에 "확인 메일을 보냈어요" 안내가 나옵니다.
3. **URL Configuration**
   - 현재 값(2026-10-07 Management API로 확인):
     - Site URL: `https://take-a-look-choi-jung-hyeon-s-projects.vercel.app/`
     - Redirect URLs: `https://takealook-skku.vercel.app/**`, `https://stock-prediction-v2-chi.vercel.app/**`, `http://localhost:3000/**`, `https://*-choi-jung-hyeon-s-projects.vercel.app/**`(Preview), `take-a-look-…` 프로젝트 주소 패턴
   - 공개 주소(`takealook-skku`)로 Site URL을 옮길지는 docs/security.md "남은 것"에서 관리합니다.
4. **API 키 확인**: Project Settings → API에서 `Project URL`과 `anon public` 키를 복사합니다.
   - ⚠️ `service_role` 키는 절대 Vercel 프론트 환경변수에 넣지 않습니다.

## 4. Vercel — 환경변수

Settings → Environment Variables:

| 이름 | 값 | 환경 |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase Project URL | Production · Preview (✅ 등록됨) |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon public 키 | Production · Preview (✅ 등록됨, 유형 Config) |

CLI로 다시 넣을 때: `vercel env add NEXT_PUBLIC_SUPABASE_ANON_KEY production --type config` (anon 키는 공개 전제 키라 Config 유형이 맞습니다).

`NEXT_PUBLIC_` 변수는 빌드할 때 들어가므로, 추가한 뒤 **Preview를 다시 배포**해야 반영됩니다(Deployments → 최신 Preview → Redeploy).

## 5. Preview에서 확인 (체크리스트)

- [ ] 로그인 화면에 "이메일로 시작"(로그인/가입 탭)과 "데모 계정으로 둘러보기"가 함께 보인다
- [ ] 가입 탭에서 새 이메일·비밀번호(6자 이상)로 가입 → `/survey`로 이동한다
- [ ] 설문 24문항 → 결과 확인 → "네, 이대로 저장" → "프로필 저장 완료"
- [ ] 대시보드로 이동 → 성향 카드에 방금 나온 유형명이 보이고, 상단에 데모 배지가 **없다**
- [ ] 로그아웃 → 로그인 탭에서 같은 계정으로 로그인 → 설문 없이 대시보드로 가고 같은 유형이 보인다(프로필 유지)
- [ ] 로그아웃 → "데모 계정으로 둘러보기" → 모든 화면 상단에 "데모 계정 · 예시 데이터" 배지가 보인다

Supabase Table Editor에서 확인할 것:

- `users`에 새 행(`auth_user_id` = 가입한 계정)
- `ips_profiles`에 새 행(`schema_version` = `1.1.0`, `profile_payload.style_axes`에 8축)
- `portfolio_holdings`는 보유 종목 화면(`/portfolio`)에서 저장한 만큼만 생깁니다

## 6. Production 적용

Preview 체크리스트를 모두 통과하면:

1. Vercel 환경변수 두 개를 Production에도 추가합니다.
2. Production을 다시 배포합니다.
3. 5번 체크리스트 중 가입·재로그인·데모 세 항목만 다시 확인합니다.

## 7. RLS 점검 결과 (2026-09-19)

`0001_init.sql`의 정책으로 충분하므로 **0004 마이그레이션은 만들지 않았습니다.**

| 테이블 | 읽기 | 쓰기 |
|---|---|---|
| `users` | 본인 행(`auth.uid() = auth_user_id`) | 본인 행 insert·update |
| `ips_profiles`, `avoided_assets`, `portfolio_holdings`, `watchlist` | 본인 `users` 행에 연결된 행만 | 같은 조건으로 insert·update |
| `stocks`, `predictions`, `prediction_features`, `market_status` | 누구나(anon 포함) 읽기 | 브라우저 쓰기 불가(백엔드 service_role만) |

- delete 정책은 없습니다. 앱은 행을 지우지 않고 `is_active = false`로 끕니다.
- 비로그인(anon)은 개인 테이블에 권한 자체가 없습니다(`revoke all` 후 `authenticated`에만 grant).

## 문제가 생기면

| 증상 | 원인·조치 |
|---|---|
| 설문 저장 시 `IPS 프로필 저장 실패 … schema_version_check` | 0003 미적용 → 1번 실행 |
| "메일 발송 한도를 넘었어요" | 비밀번호 가입·로그인을 쓰거나, 3-2의 이메일 확인을 끕니다 |
| 메일 링크를 누르면 다른 주소로 가거나 오류 | 3-3 Redirect URLs에 그 주소의 `/login`이 없음 |
| 로그인 화면에 계정 안내만 보이고 입력칸이 없음 | 환경변수가 없거나 재배포 전 → 4번 |
| 종목 상세에 "실제 상세 데이터를 불러오지 못해…" | 그 종목의 `predictions` 행이 없음(내 성향 모델 기준). seed 또는 예측 적재 필요 |
