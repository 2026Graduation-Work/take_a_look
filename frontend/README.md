> ⚠️ 이 문서의 "역할·범위·화이트박스 4패턴"은 2026-06 초기 기획이다. 현재 화면 구조는 루트 [README.md](../README.md), 화면 규칙은 [DESIGN.md](DESIGN.md)를 본다.

# 🔵 Frontend Block — 대시보드 / API / 인프라

담당: 성우

## 역할

profiling + analysis 블록의 결과를 통합하여 사용자에게 보여주는
웹 대시보드를 구현하고, API와 인프라를 담당한다.

## 범위

- 기능 명세서 → API 명세서
- 토스 스타일 대시보드 UI
- Supabase 스키마 설계
- 배포 (Vercel)

## 화이트박스 출력 4패턴 (시연 핵심)

1. 모든 추천 옆에 "근거 패널"
2. RAG 답변에 출처 강제 인용
3. 시나리오 결과에 토네이도 차트
4. AI의 한계 명시

---

## 개발 환경 (Next.js)

### 로컬 화면 확인 후 PR

기능을 추가하거나 수정할 때는 기존 UI를 유지하고 로컬에서 먼저 확인합니다.

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

브라우저에서 [http://localhost:3000](http://localhost:3000)을 엽니다. 실제 공개 DB의 시험 결과를
보려면 `.env.example`을 참고해 `.env.local`에 Supabase URL과 anon 키를 설정합니다.
환경 변수가 없으면 데모 데이터로 동작합니다. `.env.local`은 Git에 포함되지 않습니다.

에이전트는 로컬 확인 주소·작업 브랜치·변경 요약·검증 결과를 먼저 전달합니다.
화면 확인 후 사용자가 PR을 만드는 것이 기본이며, 명시적인 요청 전에는 push·PR 생성·머지·배포하지 않습니다.

This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

### Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

### Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

### Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
