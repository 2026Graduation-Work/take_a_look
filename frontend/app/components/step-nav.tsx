import { BusyLabel } from "./waiting";

export default function StepNav({
  onBack,
  backLabel = "이전",
  backDisabled = false,
  nextLabel,
  onNext,
  nextDisabled = false,
  nextBusy = false,
  nextType = "button",
  className = "",
}: {
  onBack?: () => void;
  backLabel?: string;
  backDisabled?: boolean;
  nextLabel?: string;
  onNext?: () => void;
  nextDisabled?: boolean;
  nextBusy?: boolean;
  nextType?: "button" | "submit";
  className?: string;
}) {
  const size = "min-w-[112px]";
  return (
    <div className={`flex items-center justify-between gap-3 ${className}`}>
      {onBack ? (
        <button type="button" onClick={onBack} disabled={backDisabled} className={`btn-secondary ${size}`}>
          {backLabel}
        </button>
      ) : (
        <span />
      )}
      {nextLabel && (
        <button type={nextType} onClick={onNext} disabled={nextDisabled || nextBusy} aria-busy={nextBusy || undefined} className={`btn-primary ${size}`}>
          <BusyLabel busy={nextBusy}>{nextLabel}</BusyLabel>
        </button>
      )}
    </div>
  );
}
