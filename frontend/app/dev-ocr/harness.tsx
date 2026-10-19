"use client";

import { useEffect } from "react";
import { recognize } from "@/lib/holdings-ocr/recognize";

declare global {
  interface Window {
    ocrFile?: (url: string) => Promise<{ lines: Awaited<ReturnType<typeof recognize>>; ms: number }>;
  }
}

export default function Harness() {
  useEffect(() => {
    window.ocrFile = async (url) => {
      const blob = await (await fetch(url)).blob();
      const started = performance.now();
      const lines = await recognize(blob);
      return { lines, ms: Math.round(performance.now() - started) };
    };
  }, []);
  return <p>ocr harness</p>;
}
