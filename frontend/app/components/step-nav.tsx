// 단계 이동 버튼 한 줄: 뒤로는 왼쪽 아래, 앞으로는 오른쪽 아래. 한 흐름 안의 버튼은 크기가 같다(DESIGN.md 4장).
export default function StepNav({
  onBack,
  backLabel = "이전",
  backDisabled = false,
  nextLabel,
  onNext,
  nextDisabled = false,
  nextType = "button",
  className = "",
}: {
  onBack?: () => void;
  backLabel?: string;
  backDisabled?: boolean;
  nextLabel?: string;
  onNext?: () => void;
  nextDisabled?: boolean;
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
        <button type={nextType} onClick={onNext} disabled={nextDisabled} className={`btn-primary ${size}`}>
          {nextLabel}
        </button>
      )}
    </div>
  );
}
