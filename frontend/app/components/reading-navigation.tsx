"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { readingHref, tipReturnPath } from "@/lib/tip-navigation";

type ReadingSection = "guide" | "tips" | "glossary";

export default function ReadingNavigation({ current }: { current: ReadingSection }) {
  return (
    <nav aria-label="안내 메뉴" className="bg-surface">
      <Suspense fallback={<ReadingLinks current={current} />}>
        <ReadingLinksWithOrigin current={current} />
      </Suspense>
    </nav>
  );
}

function ReadingLinksWithOrigin({ current }: { current: ReadingSection }) {
  const returnTo = tipReturnPath(useSearchParams().get("returnTo"));
  return <ReadingLinks current={current} returnTo={returnTo} />;
}

function ReadingLinks({ current, returnTo }: { current: ReadingSection; returnTo?: string }) {
  return (
    <ul className="page my-0 flex list-none flex-wrap items-center gap-x-4 sm:gap-x-6">
      {([
        ["guide", "/guide", "이용 안내"],
        ["tips", "/tips", "알고 계셨나요?"],
        ["glossary", "/glossary", "용어 모음"],
      ] as const).map(([key, href, label]) => (
        <li key={key}>
          <Link
            href={readingHref(href, returnTo)}
            aria-current={current === key ? "page" : undefined}
            className={`flex min-h-11 items-center whitespace-nowrap border-b-2 text-sm ${current === key ? "border-brand font-semibold text-brand" : "border-transparent text-body"}`}
          >
            {label}
          </Link>
        </li>
      ))}
      {returnTo && (
        <li className="ml-auto">
          {/* 안내 세 화면 어디서든 같은 자리에서 처음 보던 화면으로 돌아간다(11/28 흐름 점검) */}
          <Link href={returnTo} className="btn-text gap-1 whitespace-nowrap">
            <span aria-hidden="true">‹</span><span className="max-sm:sr-only">원래 화면으로</span>{" "}돌아가기
          </Link>
        </li>
      )}
    </ul>
  );
}
