# Frontend

기준일: 2026-11-23 (`main` `5b38d94`). 담당: 성우.

Next.js 대시보드다. 화면 구조는 루트 [README.md](../README.md), 화면 규칙은 [DESIGN.md](DESIGN.md)를 본다. 브랜치·PR 규칙은 [docs/CONTRIBUTING.md](../docs/CONTRIBUTING.md)에 있다.

## 로컬 실행

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

브라우저에서 <http://localhost:3000>을 연다.

- 처음 `pnpm dev`를 실행하면 캡처 불러오기용 글자 읽기 도구 약 55MB를 내려받는다. 출처는 이 레포 Release `ocr-assets-v1`이다. 받지 못하면 경고만 남기고 시작한다.
- 실제 공개 DB 데이터를 보려면 `.env.example`을 참고해 `.env.local`에 Supabase URL과 anon 키를 넣는다. 환경 변수가 없으면 데모 데이터로 동작한다. `.env.local`은 Git에 포함되지 않는다.

## 검증

```bash
pnpm build
pnpm test:unit
pnpm test:e2e
```
