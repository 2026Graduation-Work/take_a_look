"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { readingHref, readingReturnPath, tipHref } from "@/lib/tip-navigation";

export default function LegacyTipLink() {
  const router = useRouter();

  useEffect(() => {
    function followLegacyLink() {
      const { pathname, search, hash } = window.location;
      const returnTo = readingReturnPath(pathname, search);
      if (hash === "#terms") {
        router.replace(readingHref("/glossary", returnTo));
        return;
      }
      const id = /^#tip-([a-z0-9-]+)$/.exec(hash)?.[1];
      if (id || hash === "#beginner-tips") {
        router.replace(tipHref({ id, returnTo }));
        return;
      }
      if (hash) document.getElementById(hash.slice(1))?.scrollIntoView({ block: "start" });
    }

    followLegacyLink();
    window.addEventListener("hashchange", followLegacyLink);
    return () => window.removeEventListener("hashchange", followLegacyLink);
  }, [router]);

  return null;
}
