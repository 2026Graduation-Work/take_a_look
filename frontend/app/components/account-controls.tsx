"use client";

import Link from "next/link";
import { Suspense } from "react";
import type { InvestorProfileSummary } from "@/lib/types";
import { useOnboarding } from "./onboarding-provider";
import SignOutButton from "./sign-out-button";
import ReadingEntryLink from "./reading-entry-link";

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
        <Suspense fallback={<Link href="/guide" className={item}>이용 안내</Link>}>
          <ReadingEntryLink href="/guide" className={item}>이용 안내</ReadingEntryLink>
        </Suspense>
        <Link href="/profile#account" className={item}>
          계정 설정
        </Link>
        <SignOutButton className={`${item} w-full`} label="로그아웃" />
      </div>
    </details>
  );
}
