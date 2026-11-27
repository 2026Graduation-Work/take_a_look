"use client";

import { useId, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import { driver, type Driver } from "driver.js";
import "driver.js/dist/driver.css";
import styles from "./reading-spotlight.module.css";
import type { readingSteps, ReadingTarget } from "@/lib/evidence-reading";

type Step = ReturnType<typeof readingSteps>[number];

const STAGE_PADDING = 8;
const POPOVER_OFFSET = 12;

function makeRoomForPopover(target: HTMLElement, popup: HTMLElement, root: HTMLDivElement | null) {
  const viewportHeight = window.innerHeight;
  const anchor = target.getBoundingClientRect();
  const headerBottom = Math.max(0, root?.querySelector("header")?.getBoundingClientRect().bottom ?? 0);
  const bubble = popup.getBoundingClientRect();
  const gap = STAGE_PADDING + POPOVER_OFFSET;
  const room = bubble.height + gap;
  const fitsBeside = Math.max(anchor.left, window.innerWidth - anchor.right) >= bubble.width + gap;
  const earliestTop = headerBottom + STAGE_PADDING;
  const latestTop = viewportHeight - anchor.height - STAGE_PADDING;
  const topForBelow = latestTop - room;
  const topForAbove = Math.max(earliestTop, room + STAGE_PADDING);
  if (anchor.top >= earliestTop && anchor.top <= latestTop &&
      (anchor.top <= topForBelow || anchor.top >= topForAbove || fitsBeside)) return;

  const lastScroll = (document.scrollingElement?.scrollHeight ?? viewportHeight) - viewportHeight;
  for (const top of [topForBelow, topForAbove]) {
    const shift = anchor.top - top;
    if (top < earliestTop || top > latestTop || window.scrollY + shift < 0 || window.scrollY + shift > lastScroll) continue;
    window.scrollBy({ top: shift, behavior: "instant" });
    break;
  }
}

export default function ReadingSpotlight({
  root, step, index, count, progress, onNext, onPrevious, onClose, onError,
}: {
  root: RefObject<HTMLDivElement | null>;
  step: Step;
  index: number;
  count: number;
  progress: string;
  onNext: () => void;
  onPrevious: () => void;
  onClose: () => void;
  onError: () => void;
}) {
  const guide = useRef<Driver | null>(null);
  const visible = useRef<{ target: HTMLElement; index: number; popup?: HTMLElement } | null>(null);
  const [mount, setMount] = useState<{ host: HTMLElement; index: number; fallback: boolean } | null>(null);
  const title = useRef<HTMLHeadingElement>(null);
  const labelId = useId();
  const textId = useId();

  useLayoutEffect(() => {
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const spotlight = driver({
      animate: !motion.matches,
      duration: 180,
      overlayOpacity: 0.35,
      stagePadding: STAGE_PADDING,
      stageRadius: 12,
      popoverOffset: POPOVER_OFFSET,
      popoverClass: styles.popover,
      allowKeyboardControl: false,
      allowPageInteraction: true,
      disableActiveInteraction: true,
      overlayClickBehavior: "none",
      scrollIntoView: false,
      focus: "none",
    });
    const updateMotion = () => spotlight.setConfig({ ...spotlight.getConfig(), animate: !motion.matches });
    let resizeFrame = 0;
    const keepTargetVisible = () => {
      window.cancelAnimationFrame(resizeFrame);
      resizeFrame = window.requestAnimationFrame(() => {
        const active = visible.current;
        if (!active?.target.isConnected) return;
        const { target, popup } = active;
        const { top, bottom, left, right } = target.getBoundingClientRect();
        if (top < 0 || bottom > window.innerHeight || left < 0 || right > window.innerWidth) {
          target.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" });
        }
        if (popup?.isConnected) makeRoomForPopover(target, popup, root.current);
        spotlight.refresh();
      });
    };
    guide.current = spotlight;
    motion.addEventListener("change", updateMotion);
    window.addEventListener("resize", keepTargetVisible);
    return () => {
      window.removeEventListener("resize", keepTargetVisible);
      window.cancelAnimationFrame(resizeFrame);
      motion.removeEventListener("change", updateMotion);
      visible.current = null;
      spotlight.destroy();
      guide.current = null;
    };
  }, [root]);

  useLayoutEffect(() => {
    const spotlight = guide.current;
    if (!spotlight) return;
    const panel = root.current?.querySelector<HTMLElement>(`[data-reading-panel="${step.tab}"]:not([hidden])`);
    const tabButton = root.current?.querySelector<HTMLElement>(`#stock-tab-${step.tab}`);
    const tabList = root.current?.querySelector<HTMLElement>("[data-reading-tablist]");
    const find = (marker: ReadingTarget) => {
      if (marker === "tab-button") return tabButton;
      if (marker === "tab-list") return tabList;
      const node = panel?.querySelector<HTMLElement>(`[data-reading-target="${marker}"]`);
      return node?.getClientRects().length ? node : null;
    };
    const expected = find(step.target);
    const target = expected ?? find(step.fallback.target) ?? tabButton;
    if (!panel || !target) {
      onError();
      return;
    }
    if (visible.current?.target === target && visible.current.index === index) return;
    visible.current = { target, index };
    try {
      if (target === tabList) tabList.scrollLeft = 0;
      target.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" });
      spotlight.highlight({
        element: target,
        popover: {
          description: " ",
          side: "bottom",
          align: "start",
          onPopoverRender({ wrapper, description }) {
            const active = visible.current;
            if (active?.target === target && active.index === index) active.popup = wrapper;
            wrapper.setAttribute("aria-modal", "true");
            wrapper.setAttribute("aria-labelledby", labelId);
            wrapper.setAttribute("aria-describedby", textId);
            setMount({ host: description, index, fallback: !expected });
          },
        },
      });
    } catch {
      onError();
    }
  }, [root, step.tab, step.target, step.fallback.target, index, onError, labelId, textId]);

  useLayoutEffect(() => {
    if (!mount || mount.index !== index) return;
    const active = visible.current;
    if (active?.popup?.isConnected) makeRoomForPopover(active.target, active.popup, root.current);
    guide.current?.refresh();
    title.current?.focus({ preventScroll: true });
  }, [mount, index, root]);

  useLayoutEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" || event.key === "ArrowRight" || event.key === "ArrowLeft") {
        event.preventDefault();
        event.stopPropagation();
        if (event.key === "Escape") onClose();
        else if (!event.repeat && event.key === "ArrowLeft" && index > 0) onPrevious();
        else if (!event.repeat && event.key === "ArrowRight" && index < count - 1) onNext();
      } else if (event.key === "Tab") {
        event.preventDefault();
        event.stopPropagation();
        const buttons = mount?.index === index ? [...mount.host.querySelectorAll("button")] : [];
        if (!buttons.length) return;
        const focused = buttons.findIndex((button) => button === document.activeElement);
        const next = event.shiftKey
          ? (focused <= 0 ? buttons.length - 1 : focused - 1)
          : (focused + 1) % buttons.length;
        buttons[next].focus();
      }
    }
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [count, index, mount, onClose, onNext, onPrevious]);

  if (!mount || mount.index !== index) return null;
  return createPortal(
    <div className={styles.content}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-muted tabular-nums">{progress}</span>
        <button type="button" aria-label="안내 닫기" className="grid size-11 place-items-center rounded-sm text-muted hover:bg-track hover:text-ink" onClick={onClose}>
          <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round">
            <path d="M3 3l10 10M13 3 3 13" />
          </svg>
        </button>
      </div>
      <h2 id={labelId} ref={title} tabIndex={-1} className="m-0 text-lg font-semibold text-ink">{step.title}</h2>
      <p id={textId} className="m-0 text-sm text-body">{mount.fallback ? step.fallback.text : step.text}</p>
      <div className="mt-2 flex justify-between gap-2">
        {index > 0 && (
          <button type="button" className={styles.navButton} onClick={onPrevious}>
            <span className={styles.navFace}>이전</span>
          </button>
        )}
        <button type="button" className={`${styles.navButton} ${styles.primary} ml-auto`} onClick={onNext}>
          <span className={styles.navFace}>{index === count - 1 ? "완료" : "다음"}</span>
        </button>
      </div>
    </div>,
    mount.host,
  );
}
