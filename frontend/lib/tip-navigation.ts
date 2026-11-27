import type { TipCategory } from "./beginner-tips";

export const TIP_TOPICS = {
  all: "전체",
  calculation: "계산 착각",
  habits: "투자 습관",
  information: "정보 읽기",
  costs: "제도와 비용",
} as const satisfies Record<string, TipCategory | "전체">;

export type TipTopic = keyof typeof TIP_TOPICS;
export const TIP_PAGE_SIZE = 6;

function firstParam(value: unknown): unknown {
  return Array.isArray(value) ? value[0] : value;
}

export function tipPageCount(totalItems: number): number {
  return Math.max(1, Math.ceil(totalItems / TIP_PAGE_SIZE));
}

export function tipPage(value: unknown, totalItems: number): number {
  const param = firstParam(value);
  if (typeof param !== "string" || !/^[0-9]+$/.test(param)) return 1;
  return Math.max(1, Math.min(Number(param), tipPageCount(totalItems)));
}

export function tipTopic(value: unknown, fallback: TipTopic = "all"): TipTopic {
  const param = firstParam(value);
  return typeof param === "string" && Object.hasOwn(TIP_TOPICS, param) ? param as TipTopic : fallback;
}

export function tipDetailTopic(value: unknown, category: TipTopic): TipTopic {
  const requested = tipTopic(value, category);
  return requested === "all" ? requested : category;
}

export function topicForCategory(category: TipCategory): TipTopic {
  return (Object.keys(TIP_TOPICS) as TipTopic[]).find(topic => TIP_TOPICS[topic] === category) ?? "all";
}

export function tipReturnPath(value: unknown): string | undefined {
  const param = firstParam(value);
  if (typeof param !== "string" || !param.startsWith("/") || param.startsWith("//") || /[\\\p{Cc}]/u.test(param)) {
    return undefined;
  }
  const url = new URL(param, "https://local.invalid");
  if (!/^\/(?:profile|portfolio|performance|stocks\/[0-9A-Z]{6})?$/.test(url.pathname)) {
    return undefined;
  }
  return url.pathname + url.search + url.hash;
}

export function readingReturnPath(pathname: string, search: string, hash = ""): string | undefined {
  if (pathname === "/guide" || pathname === "/glossary" || pathname === "/tips" || pathname.startsWith("/tips/")) {
    return tipReturnPath(new URLSearchParams(search).get("returnTo"));
  }
  return tipReturnPath(pathname + search + hash);
}

export function readingHref(path: string, returnTo?: string): string {
  return returnTo ? `${path}?${new URLSearchParams({ returnTo })}` : path;
}

export function tipHref({
  id, topic, page, returnTo,
}: { id?: string; topic?: TipTopic; page?: number; returnTo?: string } = {}): string {
  const path = id ? `/tips/${encodeURIComponent(id)}` : "/tips";
  const query = new URLSearchParams();
  if (topic && (id || topic !== "all")) query.set("category", topic);
  if (page && page > 1) query.set("page", String(page));
  if (returnTo) query.set("returnTo", returnTo);
  return query.size ? `${path}?${query}` : path;
}
