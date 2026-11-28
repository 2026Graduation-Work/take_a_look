"use client";

import { Suspense, useEffect, useRef, useState, type PointerEvent } from "react";
import { BEGINNER_TIPS } from "@/lib/beginner-tips";
import { dismissTipToday, isTipDismissed, nextKstMidnight } from "@/lib/tip-dismissal";
import { tipHref } from "@/lib/tip-navigation";
import { STORAGE_KEYS } from "@/lib/storage-keys";
import ReadingEntryLink from "./reading-entry-link";
import { useDelayed } from "./waiting";

const ROTATION_MS = 5_000;
const TOUCH_PAUSE_MS = 10_000;
const COLLAPSE_MS = 180;
const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

type TipPhase = "initializing" | "visible" | "closing" | "hidden";

export default function TipStrip() {
  const [phase, setPhase] = useState<TipPhase>("initializing");
  const root = useRef<HTMLElement>(null);

  useEffect(() => {
    let timer = setTimeout(sync, 0);
    function sync() {
      clearTimeout(timer);
      const now = Date.now();
      const dismissed = isTipDismissed(now);
      setPhase(current => dismissed ? (current === "closing" ? current : "hidden") : "visible");
      timer = setTimeout(sync, nextKstMidnight(now) - now);
    }
    function onStorage(event: StorageEvent) {
      if (event.key === STORAGE_KEYS.tipDismissedOn || event.key === null) sync();
    }

    window.addEventListener("storage", onStorage);
    window.addEventListener("pageshow", sync);
    document.addEventListener("visibilitychange", sync);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("storage", onStorage);
      window.removeEventListener("pageshow", sync);
      document.removeEventListener("visibilitychange", sync);
    };
  }, []);

  useEffect(() => {
    if (phase !== "closing") return;
    const timer = setTimeout(() => setPhase("hidden"), COLLAPSE_MS);
    return () => clearTimeout(timer);
  }, [phase]);

  if (phase === "initializing" || phase === "hidden") return null;
  const closing = phase === "closing";

  function dismiss() {
    dismissTipToday(Date.now());
    const focused = document.activeElement;
    if (focused instanceof HTMLElement && root.current?.contains(focused)) focused.blur();
    setPhase(window.matchMedia(REDUCED_MOTION).matches ? "hidden" : "closing");
  }

  return (
    <section
      ref={root}
      aria-label="알고 계셨나요?"
      inert={closing}
      aria-hidden={closing || undefined}
      className={`grid bg-brand-soft/70 backdrop-blur-[20px] backdrop-saturate-[1.8] transition-[grid-template-rows] ease-out motion-reduce:transition-none ${closing ? "grid-rows-[0fr]" : "grid-rows-[1fr]"}`}
      style={{ transitionDuration: `${COLLAPSE_MS}ms` }}
    >
      <Suspense>
        <TipStripContent closing={closing} onDismiss={dismiss} />
      </Suspense>
    </section>
  );
}

function TipStripContent({ closing, onDismiss }: { closing: boolean; onDismiss: () => void }) {
  const [step, setStep] = useState(0);
  const [pause, setPause] = useState({ hover: false, touching: false, touchUntil: 0, keyboard: false });
  const tip = BEGINNER_TIPS[step % BEGINNER_TIPS.length];

  useEffect(() => {
    if (closing || pause.hover || pause.touching || pause.keyboard) return;
    const preference = window.matchMedia(REDUCED_MOTION);
    let timer: ReturnType<typeof setTimeout> | undefined;
    function schedule() {
      clearTimeout(timer);
      if (document.hidden || preference.matches) return;
      timer = setTimeout(() => setStep(current => current + 1), Math.max(ROTATION_MS, pause.touchUntil - Date.now()));
    }

    schedule();
    preference.addEventListener("change", schedule);
    document.addEventListener("visibilitychange", schedule);
    return () => {
      clearTimeout(timer);
      preference.removeEventListener("change", schedule);
      document.removeEventListener("visibilitychange", schedule);
    };
  }, [closing, pause, step]);

  function finishTouch(event: PointerEvent) {
    if (event.pointerType !== "touch") return;
    const touchUntil = Date.now() + TOUCH_PAUSE_MS;
    setPause(current => ({ ...current, touching: false, touchUntil }));
  }

  return (
    <div
      className={closing ? "min-h-0 overflow-hidden" : "min-h-0"}
      onPointerEnter={event => {
        if (event.pointerType === "mouse") setPause(current => ({ ...current, hover: true }));
      }}
      onPointerLeave={event => {
        if (event.pointerType === "mouse") setPause(current => ({ ...current, hover: false }));
      }}
      onPointerDown={event => {
        if (event.pointerType === "touch") setPause(current => ({ ...current, touching: true }));
      }}
      onPointerUp={finishTouch}
      onPointerCancel={finishTouch}
      onFocus={event => {
        if (event.target.matches(":focus-visible")) setPause(current => ({ ...current, keyboard: true }));
      }}
    >
      <div className="page grid grid-cols-[1fr_auto] items-center gap-x-3 pb-2 sm:grid-cols-[auto_1fr_auto] sm:gap-x-4 sm:pb-0">
        <span className="text-xs font-semibold text-brand">알고 계셨나요?</span>
        <div className="col-span-2 row-start-2 min-w-0 overflow-hidden focus-within:overflow-visible sm:col-span-1 sm:col-start-2 sm:row-start-1">
          <p
            key={tip.id}
            className={`m-0 min-h-[3.2em] text-xs text-body sm:min-h-0 ${step > 0 ? "motion-safe:animate-[tip-rise_180ms_ease-out]" : ""}`}
          >
            {tip.title}{" "}
            <ReadingEntryLink href={tipHref({ id: tip.id })} className="ml-2 whitespace-nowrap text-2xs text-brand hover:underline">
              자세히<span className="sr-only"> 보기</span><span aria-hidden="true"> ›</span>
            </ReadingEntryLink>
          </p>
        </div>
        <button
          type="button"
          onClick={onDismiss}
          aria-label="오늘은 그만 보기"
          title="오늘은 그만 보기"
          className="col-start-2 row-start-1 min-h-11 min-w-11 justify-self-end text-base leading-none text-muted hover:text-ink sm:col-start-3 sm:pointer-fine:min-h-8 sm:pointer-fine:min-w-8"
        >
          <span aria-hidden="true">×</span>
        </button>
      </div>
    </div>
  );
}

export function DelayedTipStrip() {
  return useDelayed(true, 1_000) ? <TipStrip /> : null;
}
