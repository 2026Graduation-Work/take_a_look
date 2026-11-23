import type { SupabaseClient } from "@supabase/supabase-js";
import { DISCLOSURE_KIND, SIGNAL_WORD, type SignalHorizon } from "./copy-glossary.ts";

const MAX_LINES = 3;
const CAUTION_KINDS = new Set(["market_action", "business_risk", "inquiry"]);
const DIRECTION = SIGNAL_WORD;

type Direction = keyof typeof DIRECTION;
type Scores = { down: number; neutral: number; up: number } | null;

export interface ChangeInput {
  stocks: { code: string; name: string }[];
  signals: { stock_code: string; batch_id: string; pack: string | null; status: string | null; scores: Scores }[];
  batchIds: [string, string?]; // [최신, 직전]
  sentiment: { stock_code: string; track: string; sentiment_date: string; sentiment_mean: number }[];
  supply: { stock_code: string; trade_date: string; foreign_investor: number; institution: number }[];
  disclosures: { stock_code: string; kind: string; title: string; filed_on: string }[];
  horizon?: SignalHorizon;
}

interface Change {
  code: string;
  name: string;
  what: string;
  how: string;
}

export interface DailyChange {
  code: string;
  name: string;
  text: string;
}

// 받침이 있으면(ㄹ 제외) '으로', 없으면 '로'
const ro = (word: string) => {
  const code = word.charCodeAt(word.length - 1) - 0xac00;
  return code >= 0 && code < 11172 && code % 28 && code % 28 !== 8 ? "으로" : "로";
};
const phrase = ({ what, how }: Change) => {
  const to = how.split(" → ")[1];
  return to ? `${what} ${to}${ro(to)}` : `${what}: ${how}`;
};

function direction(status: string | null, scores: Scores): Direction | null {
  if (status !== "available" || !scores) return null;
  const ranked = [["down", scores.down], ["flat", scores.neutral], ["up", scores.up]] as const;
  return ranked.reduce((best, next) => (next[1] > best[1] ? next : best))[0];
}

const flow = (value: number) => (value > 0 ? "순매수" : "순매도");

export function detectChanges(input: ChangeInput): DailyChange[] {
  const ranked: [number, Change][] = [];
  for (const { code, name } of input.stocks) {
    const [latestId, previousId] = input.batchIds;
    const find = (id?: string) => input.signals.find((signal) => signal.stock_code === code && signal.batch_id === id);
    const [latest, previous] = [find(latestId), previousId ? find(previousId) : undefined];
    const now = latest ? direction(latest.status, latest.scores) : null;
    const before = previous ? direction(previous.status, previous.scores) : null;
    if (now && before && now !== before && latest!.pack === previous!.pack) {
      ranked.push([0, { code, name, what: `${input.horizon === 5 ? "1주" : "4주"} 신호`, how: `${DIRECTION[before]} → ${DIRECTION[now]}` }]);
    }

    const byDate = new Map<string, number>();
    for (const row of input.sentiment.filter((item) => item.stock_code === code)) {
      if (row.track === "live" || !byDate.has(row.sentiment_date)) byDate.set(row.sentiment_date, row.sentiment_mean);
    }
    const [latestMood, previousMood] = [...byDate].sort(([left], [right]) => right.localeCompare(left));
    if (latestMood && previousMood && Math.sign(latestMood[1]) * Math.sign(previousMood[1]) < 0) {
      const word = (value: number) => (value > 0 ? "긍정" : "부정");
      ranked.push([3, { code, name, what: "뉴스 분위기", how: `${word(previousMood[1])} → ${word(latestMood[1])}` }]);
    }

    const [today, yesterday] = input.supply.filter((item) => item.stock_code === code)
      .sort((left, right) => right.trade_date.localeCompare(left.trade_date));
    if (today && yesterday) {
      for (const [key, label] of [["foreign_investor", "외국인"], ["institution", "기관"]] as const) {
        if (Math.sign(today[key]) * Math.sign(yesterday[key]) < 0) {
          ranked.push([2, { code, name, what: label, how: `${flow(yesterday[key])} → ${flow(today[key])}` }]);
        }
      }
    }

    const filings = input.disclosures.filter((item) => item.stock_code === code)
      .sort((left, right) => Number(CAUTION_KINDS.has(right.kind)) - Number(CAUTION_KINDS.has(left.kind)));
    if (filings[0]) {
      const kind = DISCLOSURE_KIND[filings[0].kind]?.label ?? "공시";
      const what = filings.length > 1 ? `새 공시 ${filings.length}건` : "새 공시";
      ranked.push([CAUTION_KINDS.has(filings[0].kind) ? 1 : 4, { code, name, what, how: disclosureHow(kind, filings[0].title) }]);
    }
  }
  const lines = new Map<string, { name: string; parts: Change[] }>();
  for (const [, change] of ranked.sort((left, right) => left[0] - right[0])) {
    const line = lines.get(change.code) ?? lines.set(change.code, { name: change.name, parts: [] }).get(change.code)!;
    line.parts.push(change);
  }
  return [...lines].slice(0, MAX_LINES).map(([code, { name, parts }]) => ({ code, name, text: parts.map(phrase).join(", ") }));
}

export function disclosureHow(kind: string, title: string): string {
  const squash = (text: string) => text.replace(/\s/g, "");
  return squash(title).includes(squash(kind)) ? title : `${title}(${kind})`;
}

export async function loadDailyChanges(
  client: Pick<SupabaseClient, "from"> | null,
  stocks: { code: string; name: string }[],
  horizon: SignalHorizon = 20,
): Promise<DailyChange[] | null> {
  if (!client || !stocks.length) return client ? [] : null;
  const codes = stocks.map(({ code }) => code);
  const { data: batches, error } = await client.from("chart_batches")
    .select("id,as_of").eq("status", "published").order("as_of", { ascending: false }).limit(2);
  if (error || !batches?.length) return null;
  const ids = (batches as { id: string; as_of: string }[]).map(({ id }) => id);
  const asOf = (batches[0] as { as_of: string }).as_of;
  const since = new Date(Date.parse(asOf) - 14 * 86_400_000).toISOString().slice(0, 10);
  const [signals, sentiment, supply, disclosures] = await Promise.all([
    client.from("chart_signal_snapshots")
      .select("stock_code,batch_id,pack:payload->>pack_id,status:payload->inference->>status,scores:payload->inference->scores")
      .in("batch_id", ids).eq("horizon", horizon).in("stock_code", codes),
    client.from("news_sentiment_daily").select("stock_code,track,sentiment_date,sentiment_mean")
      .in("stock_code", codes).gte("sentiment_date", since).not("sentiment_mean", "is", null),
    client.from("supply_demand").select("stock_code,trade_date,foreign_investor,institution")
      .in("stock_code", codes).gte("trade_date", since),
    client.from("disclosures").select("stock_code,kind,title,filed_on").in("stock_code", codes).gte("filed_on", asOf),
  ]);
  if (signals.error || sentiment.error || supply.error || disclosures.error) return null;
  return detectChanges({
    stocks,
    batchIds: [ids[0], ids[1]],
    signals: (signals.data ?? []) as ChangeInput["signals"],
    sentiment: (sentiment.data ?? []) as ChangeInput["sentiment"],
    supply: (supply.data ?? []) as ChangeInput["supply"],
    disclosures: (disclosures.data ?? []) as ChangeInput["disclosures"],
    horizon,
  });
}
