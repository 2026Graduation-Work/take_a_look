import type { ReactNode } from "react";

// loading.tsx 뼈대: 실제 배치와 같은 자리에 회색 면만. 움직이지 않는다(DESIGN.md 5장, '기다림 표시')
export function Bone({ className = "" }: { className?: string }) {
  return <div aria-hidden className={`rounded-md bg-track ${className}`} />;
}

export function SkeletonPage({ label, width, children }: { label: string; width: "wide" | "narrow" | "full"; children: ReactNode }) {
  return (
    <div className="w-full">
      <div aria-hidden className="glass-bar h-14" />
      <main className="page pb-12 pt-6" aria-busy="true">
        <p role="status" className="sr-only">{label}</p>
        <div className={`${width === "full" ? "" : `page-${width}`} flex flex-col gap-12`}>{children}</div>
      </main>
    </div>
  );
}
