import { SERVICE_NAME } from "@/lib/brand";
import LogoMark from "./LogoMark";

export default function Wordmark({
  size = 24,
  className = "",
  compact = false,
}: {
  size?: number;
  className?: string;
  compact?: boolean;
}) {
  return (
    <span className={`inline-flex items-center font-semibold text-brand ${className}`} style={{ gap: size / 4 }}>
      <LogoMark size={size} />
      <span className={compact ? "max-sm:sr-only" : undefined}>{SERVICE_NAME}</span>
    </span>
  );
}
