"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";

export default function TipList({ tips }: { tips: readonly { id: string; title: string; summary: string; href: string }[] }) {
  const listRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    function restoreTip() {
      const { hash } = window.location;
      if (!hash.startsWith("#tip-")) return;
      const item = document.getElementById(hash.slice(1));
      if (!item || !listRef.current?.contains(item)) return;
      const link = item.querySelector("a");
      if (!link) return;
      item.scrollIntoView({ block: "start" });
      link.focus({ preventScroll: true });
    }

    restoreTip();
    window.addEventListener("hashchange", restoreTip);
    return () => window.removeEventListener("hashchange", restoreTip);
  }, [tips]);

  return (
    <ul ref={listRef} aria-label="투자 팁 목록" className="m-0 flex list-none flex-col gap-6 p-0">
      {tips.map(({ id, href, title, summary }) => (
        <li key={id} id={`tip-${id}`} className="scroll-mt-20">
          <Link
            href={href}
            aria-labelledby={`tip-title-${id}`}
            aria-describedby={`tip-summary-${id}`}
            className="group surface flex min-h-11 items-center gap-4 px-4 py-4 text-ink sm:px-6"
          >
            <div className="flex min-w-0 flex-1 flex-col gap-2 wrap-anywhere">
              <h2 id={`tip-title-${id}`} className="m-0 text-xl font-semibold group-hover:underline group-hover:underline-offset-4">
                {title}
              </h2>
              <p id={`tip-summary-${id}`} className="m-0 pl-3 text-sm text-muted">{summary}</p>
            </div>
            <span aria-hidden="true" className="shrink-0 text-xl text-muted">›</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
