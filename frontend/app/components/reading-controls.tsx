"use client";

import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import type { ReadingTab, readingSteps } from "@/lib/evidence-reading";
import { READING_ERROR, READING_REPLAY_HASH, READING_START_EVENT, readingProgress } from "@/lib/evidence-reading";
import { claimReadingHint, readReadingHistory, recordReadingOutcome } from "@/lib/evidence-reading-history";

type Step = ReturnType<typeof readingSteps>[number];
type Spotlight = typeof import("./reading-spotlight").default;

type ReadingState =
  | { kind: "idle" }
  | { kind: "loading"; steps: Step[] }
  | { kind: "reading"; steps: Step[]; index: number; Spotlight: Spotlight };

export function useEvidenceReading({
  historyKey, invite, code, steps, selectTab, root, replayButton,
}: {
  historyKey: string | null;
  invite: boolean;
  code: string;
  steps: Step[];
  selectTab: (tab: ReadingTab) => void;
  root: RefObject<HTMLDivElement | null>;
  replayButton: RefObject<HTMLButtonElement | null>;
}) {
  const [state, setState] = useState<ReadingState>({ kind: "idle" });
  const [entry, setEntry] = useState<"invitation" | "hint" | null>(null);
  const [error, setError] = useState("");
  const startButton = useRef<HTMLButtonElement | null>(null);
  const restoreFocus = useRef(false);

  useEffect(() => {
    if (!historyKey || !invite) return;
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      if (readReadingHistory(historyKey).status === "new") setEntry("invitation");
      else if (claimReadingHint(historyKey, code)) setEntry("hint");
    });
    return () => { active = false; };
  }, [historyKey, code, invite]);

  useEffect(() => {
    if (state.kind !== "loading") return;
    let active = true;
    function cancel(event: KeyboardEvent) {
      if (event.key === "Escape") {
        restoreFocus.current = true;
        setState({ kind: "idle" });
      }
    }
    window.addEventListener("keydown", cancel);
    import("./reading-spotlight")
      .then(({ default: Spotlight }) => {
        if (!active) return;
        selectTab("overview");
        setState({ kind: "reading", index: 0, steps: state.steps, Spotlight });
      })
      .catch(() => {
        if (!active) return;
        restoreFocus.current = true;
        setError(READING_ERROR);
        setState({ kind: "idle" });
      });
    return () => {
      active = false;
      window.removeEventListener("keydown", cancel);
    };
  }, [state, selectTab]);

  useLayoutEffect(() => {
    if (state.kind !== "idle" || !restoreFocus.current) return;
    restoreFocus.current = false;
    const button = startButton.current;
    (button?.isConnected ? button : replayButton.current)?.focus();
  }, [state, replayButton]);

  function start(invoker: HTMLButtonElement | null) {
    if (state.kind !== "idle" || !historyKey) return;
    startButton.current = invoker;
    setError("");
    document.dispatchEvent(new Event(READING_START_EVENT));
    setState({ kind: "loading", steps });
  }

  useEffect(() => {
    if (!historyKey || state.kind !== "idle" || window.location.hash !== READING_REPLAY_HASH) return;
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search);
      start(replayButton.current);
    });
    return () => { active = false; };
  });

  function close(outcome: "completed" | "dismissed" | "error") {
    if (historyKey && outcome !== "error") {
      recordReadingOutcome(historyKey, code, outcome);
      setEntry(null);
    }
    if (outcome === "error") setError(READING_ERROR);
    restoreFocus.current = true;
    setState({ kind: "idle" });
  }

  function dismiss(invoker: HTMLButtonElement) {
    startButton.current = invoker;
    close("dismissed");
  }

  function move(delta: -1 | 1) {
    if (state.kind !== "reading") return;
    const index = state.index + delta;
    if (index === state.steps.length) {
      close("completed");
      return;
    }
    if (index < 0) return;
    selectTab(state.steps[index].tab);
    setState({ ...state, index });
  }

  const planned = state.kind === "reading" ? state.steps[state.index] : null;
  const current = planned && (steps.find(({ id }) => id === planned.id)
    ?? { ...planned, target: planned.fallback.target, text: planned.fallback.text });

  const spotlight = state.kind === "reading" && current && (
    <state.Spotlight
      root={root}
      step={current}
      index={state.index}
      count={state.steps.length}
      progress={readingProgress(state.steps, state.index)}
      onNext={() => move(1)}
      onPrevious={() => move(-1)}
      onClose={() => close("dismissed")}
      onError={() => close("error")}
    />
  );

  return { start, dismiss, state: state.kind, phase: current?.phase, entry, error, spotlight };
}
