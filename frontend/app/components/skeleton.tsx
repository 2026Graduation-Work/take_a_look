import type { ReactNode } from "react";

export function Bone({ className = "" }: { className?: string }) {
  return <div aria-hidden className={`rounded-md bg-track ${className}`} />;
}

export function SkeletonPage({
  label,
  width,
  beneathHeader,
  children,
}: {
  label: string;
  width: "wide" | "narrow" | "full";
  beneathHeader?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="w-full">
      <div aria-hidden className="glass-bar h-14" />
      {beneathHeader}
      <main className="page pb-12 pt-6" aria-busy="true">
        <p role="status" className="sr-only">{label}</p>
        <div className={`${width === "full" ? "" : `page-${width}`} flex flex-col gap-12`}>{children}</div>
      </main>
    </div>
  );
}
