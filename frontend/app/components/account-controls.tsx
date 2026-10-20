"use client";

import Link from "next/link";
import type { InvestorProfileSummary } from "@/lib/types";
import { useOnboarding } from "./onboarding-provider";
import SignOutButton from "./sign-out-button";

// 헤더 오른쪽: 이름 하나. 누르면 계정 메뉴(보유 종목, 내 투자 성향, 이용 안내, 계정 설정, 로그아웃).
// profile이 없는 화면(이용 안내)은 저장된 이름만 쓴다.
// 다시 진단은 내 투자 성향 화면의 버튼 하나로만 간다(같은 목적지의 길은 하나)
export default function AccountControls({ profile }: { profile?: InvestorProfileSummary }) {
  const { state } = useOnboarding();
  const displayName = state.displayName?.trim() || profile?.displayName || "내 계정";
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
        <Link href="/portfolio" className={item}>
          보유 종목
        </Link>
        <Link href="/profile" className={item}>
          내 투자 성향
        </Link>
        <Link href="/guide" className={item}>
          이용 안내
        </Link>
        <Link href="/profile#account" className={item}>
          계정 설정
        </Link>
        <SignOutButton className={`${item} w-full`} label="로그아웃" />
      </div>
    </details>
  );
}
