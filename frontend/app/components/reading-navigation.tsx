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
    <ul className="page my-0 flex list-none gap-6">
      {([
        ["guide", "/guide", "이용 안내"],
        ["tips", "/tips", "알고 계셨나요?"],
        ["glossary", "/glossary", "용어 모음"],
      ] as const).map(([key, href, label]) => (
        <li key={key}>
          <Link
            href={readingHref(href, returnTo)}
            aria-current={current === key ? "page" : undefined}
            className={`flex min-h-11 items-center border-b-2 text-sm ${current === key ? "border-brand font-semibold text-brand" : "border-transparent text-body"}`}
          >
            {label}
          </Link>
        </li>
      ))}
    </ul>
  );
}
