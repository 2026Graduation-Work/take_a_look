import Link from "next/link";
import type { ReactNode } from "react";
import Wordmark from "@/components/brand/Wordmark";

export default function BrandHeader({ children }: { children?: ReactNode }) {
  return (
    <header className="glass-bar sticky top-0 z-50">
      <div className="page flex min-h-14 flex-wrap items-center gap-x-5 gap-y-2 py-2 sm:h-14 sm:flex-nowrap sm:py-0">
        <Link href="/" aria-label="대시보드" className="flex min-h-11 flex-none items-center text-lg hover:no-underline">
          <Wordmark size={26} />
        </Link>
        {children}
      </div>
    </header>
  );
}
