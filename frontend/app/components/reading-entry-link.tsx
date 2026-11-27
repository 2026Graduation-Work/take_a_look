"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useSyncExternalStore, type ReactNode } from "react";
import { readingHref, readingReturnPath } from "@/lib/tip-navigation";

function subscribeToFragment(onChange: () => void) {
  window.addEventListener("hashchange", onChange);
  window.addEventListener("popstate", onChange);
  return () => {
    window.removeEventListener("hashchange", onChange);
    window.removeEventListener("popstate", onChange);
  };
}

export default function ReadingEntryLink({ href, className, children }: {
  href: string;
  className: string;
  children: ReactNode;
}) {
  const pathname = usePathname();
  const params = useSearchParams();
  const router = useRouter();
  const hash = useSyncExternalStore(subscribeToFragment, () => window.location.hash, () => "");
  const search = params.size ? `?${params}` : "";
  const entryHref = readingHref(href, readingReturnPath(pathname, search, hash));

  return (
    <Link
      href={entryHref}
      className={className}
      onNavigate={event => {
        const { pathname, search, hash } = window.location;
        const liveHref = readingHref(href, readingReturnPath(pathname, search, hash));
        if (liveHref === entryHref) return;
        event.preventDefault();
        router.push(liveHref);
      }}
    >
      {children}
    </Link>
  );
}
