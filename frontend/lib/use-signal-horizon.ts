"use client";

import { useSyncExternalStore } from "react";
import type { SignalHorizon } from "./copy-glossary";
import { STORAGE_KEYS } from "./storage-keys";

let memoryHorizon: SignalHorizon = 20;
let storageWriteFailed = false;
const listeners = new Set<() => void>();
const notify = () => listeners.forEach(listener => listener());
function subscribe(listener: () => void) {
  listeners.add(listener);
  const storage = (event: StorageEvent) => {
    if (event.key === STORAGE_KEYS.signalHorizon || event.key === null) {
      storageWriteFailed = false;
      listener();
    }
  };
  window.addEventListener("storage", storage);
  return () => { listeners.delete(listener); window.removeEventListener("storage", storage); };
}
function read(): SignalHorizon {
  if (storageWriteFailed) return memoryHorizon;
  try { return localStorage.getItem(STORAGE_KEYS.signalHorizon) === "5" ? 5 : 20; }
  catch { return memoryHorizon; }
}
function choose(next: SignalHorizon) {
  memoryHorizon = next;
  try { localStorage.setItem(STORAGE_KEYS.signalHorizon, String(next)); storageWriteFailed = false; }
  catch { storageWriteFailed = true; }
  notify();
}
export function useSignalHorizon() {
  return [useSyncExternalStore(subscribe, read, () => 20 as SignalHorizon), choose] as const;
}
