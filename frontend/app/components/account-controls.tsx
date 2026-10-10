"use client";

import Link from "next/link";
import type { InvestorProfileSummary } from "@/lib/types";
import { useOnboarding } from "./onboarding-provider";
import SignOutButton from "./sign-out-button";

// 헤더 오른쪽: 이름 하나. 누르면 계정 메뉴(다시 진단·보유 종목 편집·계정 관리·로그아웃). 유형 이름은 대시보드 맨 위 한 줄에 둔다.
export default function AccountControls({ profile }: { profile: InvestorProfileSummary }) {
  const { state } = useOnboarding();
  const displayName = state.displayName?.trim() || profile.displayName;
  const item = "block px-4 py-3 text-left text-sm text-ink hover:bg-field hover:text-ink hover:no-underline";

  return (
    <details className="relative ml-auto flex-none">
      <summary
        aria-label={`${displayName} 계정 메뉴`}
        className="flex min-h-11 cursor-pointer list-none items-center gap-1 whitespace-nowrap text-xs font-medium text-body hover:text-ink"
      >
        {displayName}
        <span aria-hidden className="text-muted">▾</span>
      </summary>
      <div className="glass bg-white/90 absolute right-0 top-11 z-50 flex w-48 flex-col overflow-hidden rounded-md py-1">
        <Link href="/survey" className={item}>
          내 성향 다시 진단
        </Link>
        <Link href="/portfolio" className={item}>
          보유 종목 편집
        </Link>
        <Link href="/profile#account" className={item}>
          계정 관리
        </Link>
        <SignOutButton className={`${item} w-full`} label="로그아웃" />
      </div>
    </details>
  );
}
