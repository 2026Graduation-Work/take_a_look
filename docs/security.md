# 보안·개인정보 점검 (2026-10-06)

## 저장되는 개인 정보
| 항목 | 위치 | 누가 읽고 쓰나 |
|---|---|---|
| 이메일·비밀번호(해시)·이름(`full_name`) | Supabase Auth `auth.users` | Supabase Auth만. 비밀번호 원문은 저장되지 않음 |
| 표시 이름 | `public.users.display_name` | 본인(RLS `auth.uid() = auth_user_id`) |
| 성향 진단 결과 | `public.ips_profiles` | 본인(RLS) |
| 보유 종목·평단 | `public.portfolio_holdings` | 본인(RLS) |
| 관심 종목·판단 메모 | `public.watchlist`·`public.stock_notes` | 본인(RLS) |
| 같은 값의 브라우저 사본 | `localStorage` | 이 브라우저. 로그아웃 시 삭제 |

- 모든 테이블에 RLS가 켜져 있고, 개인 테이블은 `anon` 권한을 회수하고 `authenticated`에 본인 행만 허용한다(`supabase/migrations/0001`, `0006`).
- 시세·예측·뉴스 같은 공개 데이터는 읽기만 열려 있고, 쓰기는 GitHub Actions의 `SUPABASE_SECRET_KEY`(서비스 키)만 한다. 서비스 키는 브라우저 코드에 없다.
- 브라우저에는 공개용 키(`NEXT_PUBLIC_SUPABASE_ANON_KEY`)만 있다. 이 키로는 RLS를 넘을 수 없다.

## 이번에 보강한 것
- 보안 헤더: 다른 사이트의 iframe 삽입 차단(`frame-ancestors 'none'`, `X-Frame-Options`), `nosniff`, `Referrer-Policy`, 카메라·마이크·위치 차단(`frontend/next.config.ts`).
- 로그아웃 시 보유 종목 브라우저 사본도 삭제(공용 PC 대비). 로그인하면 Supabase에서 다시 읽는다.
- 가입 비밀번호 8자 이상(화면), 가입 화면에 저장 항목·용도 안내.

## 남은 것
- **계정 삭제**: 지금은 사용자가 스스로 계정과 데이터를 지울 수 없다. `delete_my_account()` 함수 마이그레이션 초안과 화면 버튼은 별도 PR(적용 전 확인 필요).
- **Supabase 대시보드 설정**(Authentication → Providers/Rate Limits, 팀 관리자가 확인):
  - Email: Confirm email 켜기, Minimum password length 8
  - URL Configuration: Site URL과 Redirect URLs를 `https://takealook-skku.vercel.app/**`만으로
  - Rate limits 기본값 유지, 가입 남용이 보이면 Attack Protection의 CAPTCHA(Cloudflare Turnstile, 무료) 켜기
- 세션 토큰은 supabase-js 기본값대로 `localStorage`에 있다. XSS가 막는 핵심이라 `dangerouslySetInnerHTML`은 쓰지 않는다.
