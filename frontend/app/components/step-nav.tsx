import { BusyLabel } from "./waiting";

// 단계 이동 버튼 한 줄: 뒤로는 왼쪽 아래, 앞으로는 오른쪽 아래. 한 흐름 안의 버튼은 크기가 같다(DESIGN.md 4장).
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
  nextBusy?: boolean; // 누른 뒤 기다리는 중: 눌린 상태로 막고(중복 제출 방지) 글자 자리에 도는 표시
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
