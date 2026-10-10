"use client";

// 되돌리기 어려운 행동의 확인 창(DESIGN.md 0-1 ④). window.confirm과 달리 주 버튼에 실제 행동을 쓴다.
// 네이티브 dialog라 포커스 가두기·Esc 닫기를 브라우저가 맡는다(holdings-editor.tsx 종목 추가 시트와 같은 방식).

import { useId, useRef, type ReactNode } from "react";
import StepNav from "./step-nav";

export default function ConfirmButton({
  children,
  title,
  message,
  confirmLabel,
  onConfirm,
  ask = true,
  className,
  disabled,
  "aria-label": ariaLabel,
}: {
  children: ReactNode;
  title: string;
  message: string;
  confirmLabel: string;
  onConfirm: () => void;
  ask?: boolean;
  className?: string;
  disabled?: boolean;
  "aria-label"?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  return (
    <>
      <button
        type="button"
        aria-label={ariaLabel}
        disabled={disabled}
        onClick={() => (ask ? ref.current?.showModal() : onConfirm())}
        className={className}
      >
        {children}
      </button>
      <dialog
        ref={ref}
        aria-labelledby={`${id}-title`}
        aria-describedby={`${id}-message`}
        className="m-auto w-[min(400px,calc(100vw-32px))] rounded-xl bg-white p-0 text-ink shadow-modal backdrop:bg-black/30"
      >
        <form
          method="dialog"
          onSubmit={(event) => {
            event.preventDefault();
            ref.current?.close();
            onConfirm();
          }}
          className="flex flex-col gap-4 p-6"
        >
          <h2 id={`${id}-title`} className="text-lg font-semibold">
            {title}
          </h2>
          <p id={`${id}-message`} className="m-0 text-sm text-body">
            {message}
          </p>
          <StepNav onBack={() => ref.current?.close()} backLabel="취소" nextType="submit" nextLabel={confirmLabel} />
        </form>
      </dialog>
    </>
  );
}
