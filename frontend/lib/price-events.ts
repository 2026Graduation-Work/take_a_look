export type DatedClose = { date: string; close: number; volume: number };

export const PRICE_EVENT_METHOD = "daily-log-std-250-v1";
export const PRICE_EVENT_MULTIPLIER = 2;
export const PRICE_EVENT_HISTORY_SIZE = 60;

export type PriceEventBasis = {
  method: typeof PRICE_EVENT_METHOD;
  dailySigma: number;
  returnCount: number;
  periodStart: string;
  periodEnd: string;
  inputSha256: string;
  previousBar: DatedClose | null;
};

export type DisclosureWindow = {
  from: string;
  through: string;
  endReason: "next_session_included" | "snapshot_boundary";
};

type PriceMove = {
  date: string;
  previousDate: string;
  close: number;
  changePercent: number;
  disclosureWindow: DisclosureWindow;
};
export type PriceMoveResult =
  | { status: "ready"; moves: PriceMove[]; evaluatedDays: number; excludedDays: number }
  | { status: "unavailable"; reason: "missing_basis" | "invalid_basis" | "incomplete_sessions" | "no_evaluable_returns" };

export function isCalendarDate(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const time = Date.parse(value);
  return Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === value;
}

export function selectPriceMoves(
  history: readonly DatedClose[],
  basis: PriceEventBasis | undefined,
  dataAsOf: string,
): PriceMoveResult {
  if (!basis) return { status: "unavailable", reason: "missing_basis" };
  if (basis.periodEnd !== dataAsOf || !Number.isFinite(basis.dailySigma) || basis.dailySigma <= 0 ||
      !Number.isInteger(basis.returnCount) || basis.returnCount < 60 || basis.returnCount > 250) {
    return { status: "unavailable", reason: "invalid_basis" };
  }
  const prices = history.slice(-PRICE_EVENT_HISTORY_SIZE);
  const previousBar = history.at(-PRICE_EVENT_HISTORY_SIZE - 1) ?? basis.previousBar;
  const dates = previousBar ? [previousBar, ...prices] : prices;
  if (prices.at(-1)?.date !== dataAsOf ||
      dates.some((bar, index) => !isCalendarDate(bar.date) ||
        (index > 0 && bar.date <= dates[index - 1].date) ||
        !Number.isFinite(bar.close) || bar.close <= 0 ||
        !Number.isFinite(bar.volume) || bar.volume < 0)) {
    return { status: "unavailable", reason: "incomplete_sessions" };
  }

  let evaluatedDays = 0;
  let excludedDays = previousBar ? 0 : 1;
  const candidates: { move: PriceMove; magnitude: number; roundoff: number }[] = [];
  for (const [index, bar] of prices.entries()) {
    const previous = index === 0 ? previousBar : prices[index - 1];
    if (!previous) continue;
    const delta = bar.close - previous.close;
    const change = delta / previous.close;
    const changePercent = change * 100;
    if (previous.volume === 0 || bar.volume === 0 || !Number.isFinite(changePercent)) {
      excludedDays += 1;
      continue;
    }
    evaluatedDays += 1;
    const thresholdPrice = previous.close * (PRICE_EVENT_MULTIPLIER * basis.dailySigma);
    const deltaMagnitude = Math.abs(delta);
    // The adjustment factor divides and multiplies each close. Carry that roundoff into the price comparison.
    const priceRoundoff = Number.EPSILON * bar.close + Number.EPSILON * previous.close + Number.EPSILON * deltaMagnitude;
    if (deltaMagnitude - thresholdPrice <= priceRoundoff + Number.EPSILON * thresholdPrice) continue;

    const magnitude = Math.abs(change);
    const next = prices[index + 1];
    candidates.push({
      magnitude,
      roundoff: priceRoundoff / previous.close + Number.EPSILON * magnitude,
      move: {
        date: bar.date,
        previousDate: previous.date,
        close: bar.close,
        changePercent,
        disclosureWindow: {
          from: previous.date,
          through: next?.date ?? dataAsOf,
          endReason: next ? "next_session_included" : "snapshot_boundary",
        },
      },
    });
  }
  if (!evaluatedDays) return { status: "unavailable", reason: "no_evaluable_returns" };

  const moves: PriceMove[] = [];
  const newestFirst = (a: PriceMove, b: PriceMove) => b.date.localeCompare(a.date);
  let remaining = candidates.sort((a, b) => b.magnitude - a.magnitude);
  while (remaining.length && moves.length < 3) {
    const leader = remaining[0];
    const tied: PriceMove[] = [];
    const weaker: typeof candidates = [];
    for (const candidate of remaining) {
      // Compare with the strongest remaining return, so roundoff cannot chain adjacent ties.
      if (leader.magnitude - candidate.magnitude <= leader.roundoff + candidate.roundoff) tied.push(candidate.move);
      else weaker.push(candidate);
    }
    moves.push(...tied.sort(newestFirst).slice(0, 3 - moves.length));
    remaining = weaker;
  }
  moves.sort(newestFirst);
  return { status: "ready", moves, evaluatedDays, excludedDays };
}
