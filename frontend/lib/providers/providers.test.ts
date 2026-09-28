import assert from "node:assert/strict";
import { test } from "node:test";
import { investorStyleAxes, portfolioHoldings, stockDetails } from "../mock-data.ts";
import { classifyBit } from "../profiling/bit.ts";
import { selectNudges } from "../profiling/nudges.ts";
import type { StyleAxes } from "../types.ts";
import SAMSUNG_NEWS_TRACK from "./sentiment-005930.json" with { type: "json" };
import KAKAO_NEWS_TRACK from "./sentiment-035720.json" with { type: "json" };
import HYUNDAI_NEWS_TRACK from "./sentiment-005380.json" with { type: "json" };
import CELLTRION_NEWS_TRACK from "./sentiment-068270.json" with { type: "json" };
import {
  contributionProvider,
  financialProvider,
  loadStockInsights,
  marketSentimentView,
  sentimentProvider,
  supplyDemandProvider,
  toNudgeMarket,
} from "./index.ts";

const CODES = ["005930", "005380"];

for (const [code, companyName, track] of [
  ["005930", "삼성전자", SAMSUNG_NEWS_TRACK],
  ["005380", "현대차", HYUNDAI_NEWS_TRACK],
  ["035720", "카카오", KAKAO_NEWS_TRACK],
  ["068270", "셀트리온", CELLTRION_NEWS_TRACK],
] as const) {
  test(`${companyName} 감성 JSON은 백엔드 historical track 계약을 쓴다`, () => {
    assert.equal(track.schema_version, "1.0");
    assert.equal(track.track, "historical");
    assert.deepEqual(track.scope, { ticker: code, company_name: companyName });
    assert.equal(track.source, "bigkinds");
    assert.equal(track.backend, "kr-finbert");
    assert.equal(track.timeline.length, 20);
    assert.ok(!("days" in track));
  });
}

test("데모 4종목은 BigKinds 과거 감성 20개 관측치를 반환한다", async () => {
  for (const code of ["005930", "005380", "035720", "068270"]) {
    const sentiment = await sentimentProvider(code);
    assert.equal(sentiment?.days.length, 20, code);
    assert.equal(sentiment?.source, "real", code);
    assert.ok(sentiment?.days.every(({ score }) => score >= -1 && score <= 1), code);
  }
});

for (const code of CODES) {
  test(`${code}: 4개 Provider가 값을 반환한다`, async () => {
    const supply = await supplyDemandProvider(code);
    assert.equal(supply?.length, 20);
    assert.equal(supply?.at(-1)?.date, "2025-12-30"); // 데모 기준일
    assert.deepEqual(
      supply?.map(({ date }) => date),
      [...(supply ?? [])].map(({ date }) => date).sort(),
    );

    const sentiment = await sentimentProvider(code);
    assert.equal(sentiment?.days.length, 20);
    // 4종목 모두 실제 BigKinds 기사 집계. 기사 제목은 삼성전자(기존)만 있고 나머지는 커밋하지 않는다.
    assert.equal(sentiment?.headlines.length, code === "005930" ? 3 : 0);
    assert.equal(sentiment?.source, "real");
    assert.ok(sentiment?.days.every(({ score }) => score >= -1 && score <= 1));

    const contributions = await contributionProvider(code);
    const total = contributions?.reduce((sum, { share }) => sum + share, 0) ?? 0;
    assert.ok(Math.abs(total - 100) < 1e-9);
    assert.deepEqual(
      new Set(contributions?.map(({ category }) => category)),
      new Set(["technical", "financial", "sentiment", "supply"]),
    );
    assert.ok(contributions?.every(({ description }) => description.length > 0));

    const financial = await financialProvider(code);
    assert.ok((financial?.metrics.length ?? 0) > 0);
  });
}

test("대상 외 종목은 null", async () => {
  const { supply, sentiment, contributions, financial } = await loadStockInsights("000660");
  assert.deepEqual(
    { supply, sentiment, contributions, financial },
    { supply: null, sentiment: null, contributions: null, financial: null },
  );
});

test("수급: 데모 4종목은 실데이터 20영업일(기준일까지, 12-25 휴장 제외) 정수 수량", async () => {
  for (const code of ["005930", "005380", "035720", "068270"]) {
    const supply = (await supplyDemandProvider(code)) ?? [];
    assert.equal(supply.length, 20, code);
    assert.equal(supply[0].date, "2025-12-02", code);
    assert.equal(supply.at(-1)?.date, "2025-12-30", code);
    assert.ok(!supply.some(({ date }) => date === "2025-12-25"), code);
    for (const day of supply) {
      for (const value of [day.retail, day.foreign, day.institution]) assert.ok(Number.isInteger(value), `${code} ${day.date}`);
    }
    const { provenance } = await loadStockInsights(code);
    assert.deepEqual(provenance.supply, { kind: "real", source: "네이버 금융 투자자별 매매동향", asOf: "2025-12-30" });
  }
});

test("출처: 감성은 데모 4종목 실데이터, 모델 근거는 픽스처", async () => {
  const samsung = await loadStockInsights("005930");
  assert.deepEqual(samsung.provenance.sentiment, {
    kind: "real",
    source: "BigKinds · KR-FinBERT · 저장된 데이터",
    asOf: samsung.sentiment?.days.at(-1)?.date,
  });
  for (const key of ["contributions"] as const) {
    assert.equal(samsung.provenance[key].kind, "fixture", key);
  }
  for (const code of ["005380", "035720", "068270"]) {
    const insights = await loadStockInsights(code);
    assert.equal(insights.provenance.sentiment.kind, "real", code);
    assert.match(insights.provenance.sentiment.source, /저장된 데이터/, code);
    assert.equal(insights.provenance.sentiment.asOf, insights.sentiment?.days.at(-1)?.date, code);
  }
});

test("가격 흐름 분위기: 데모 4종목은 실데이터 스냅샷에서 구간 말을 갖는다", async () => {
  for (const code of ["005930", "005380", "035720", "068270"]) {
    const { psychology } = await loadStockInsights(code);
    assert.ok(psychology, code);
    assert.equal(psychology.provenance.kind, "real");
    assert.equal(psychology.provenance.asOf, "2025-12-30");
    assert.ok(psychology.axis >= -1 && psychology.axis <= 1);
    assert.ok(["많이 들뜸", "조금 들뜸", "차분함", "조금 움츠러듦", "많이 움츠러듦"].includes(psychology.word));
  }
  assert.equal((await loadStockInsights("000660")).psychology, null);
});

// 기준일(2025-12-30) 시점에 이미 공시된 사업보고서만 쓰고(룩어헤드 방지), 지표는 상식 범위 안이다.
// 범위는 backend value_pipeline agents._PLAUSIBLE과 같다(화면 단위로 환산).
const FINANCIAL_RANGE: Record<string, [number, number]> = {
  per: [0.5, 500],
  pbr: [0.1, 100],
  roe: [-100, 200],
  operating_margin: [-100, 100],
  debt_ratio: [0, 5000],
  revenue_growth: [-100, 1000],
};

test("재무: 데모 4종목은 기준일 전에 공시된 FY2024 사업보고서의 6지표, 값은 상식 범위", async () => {
  for (const code of ["005930", "005380", "035720", "068270"]) {
    const { financial, provenance } = await loadStockInsights(code);
    assert.ok(financial, code);
    assert.deepEqual(provenance.financial, {
      kind: "real",
      source: "DART 사업보고서 · 저장된 데이터",
      asOf: "2025-12-30",
    });
    assert.match(financial.period, /^2024 사업연도 · 연결재무제표 · 사업보고서 2025-0[1-9]-\d{2} 공시/);
    const filedAt = financial.period.match(/사업보고서 (\d{4}-\d{2}-\d{2}) 공시/)?.[1] ?? "";
    assert.ok(filedAt <= "2025-12-30", `${code} 공시일 ${filedAt}`);
    assert.deepEqual(financial.metrics.map(({ key }) => key), Object.keys(FINANCIAL_RANGE));
    for (const { key, value, note, basis } of financial.metrics) {
      assert.ok(basis.length > 0, `${code} ${key} 계산 근거`);
      if (value === null) {
        assert.ok(note, `${code} ${key}: 확인 불가면 이유가 있다`);
        continue;
      }
      const [low, high] = FINANCIAL_RANGE[key];
      assert.ok(value >= low && value <= high, `${code} ${key}=${value}`);
    }
  }
  // 카카오 FY2024는 순손실 → PER은 계산하지 않는다(0이나 음수로 채우지 않음)
  const kakao = await financialProvider("035720");
  assert.deepEqual(kakao?.metrics.find(({ key }) => key === "per"), {
    key: "per",
    label: "PER",
    unit: "배",
    value: null,
    note: "순손실이라 계산하지 않음",
    basis: kakao?.metrics.find(({ key }) => key === "per")?.basis,
  });
});

function minjiWith(overrides: Record<string, number>): StyleAxes {
  return {
    ...investorStyleAxes,
    axes: investorStyleAxes.axes.map((axis) =>
      axis.axis_id in overrides ? { ...axis, ratio: overrides[axis.axis_id] } : axis,
    ),
  };
}

async function samsungNudges(styleAxes: StyleAxes) {
  const detail = stockDetails["005930"];
  const market = toNudgeMarket(detail, await loadStockInsights("005930"), portfolioHoldings);
  assert.ok(market);
  return selectNudges(classifyBit(styleAxes), market).map(({ id }) => id);
}

test("김민지 + 삼성전자: 넛지가 1개 이상 발화한다", async () => {
  const fired = await samsungNudges(investorStyleAxes);
  assert.ok(fired.length >= 1);
  assert.deepEqual(fired, EXPECTED_MINJI_SAMSUNG);
});

test("김민지 + 삼성전자: information_reliance를 0.3으로 올리면 수급 넛지 N02가 새로 발화하고 다른 축의 N07이 함께 보인다", async () => {
  assert.ok(!(await samsungNudges(investorStyleAxes)).includes("N02"));
  // N03(최근 5일 중 기관 순매수 4일 이상)은 실데이터에서 3일이라 시장 조건이 거짓이다
  assert.deepEqual(await samsungNudges(minjiWith({ information_reliance: 0.3 })), ["N02", "N07"]);
});

// urgency +0.44 × 감성 창 마지막 날 |Δ| >= p90(실제 날짜 구간) → N07.
// N04(변동성 백분위 0.48)·N05(3개월 고점 대비, 실데이터 시세)는 시장 조건이 거짓이라 발화하지 않는다.
// sentiment-fixture.ts가 다시 생성되면 재확인한다.
const EXPECTED_MINJI_SAMSUNG: string[] = ["N07"];

type SupabaseResponse = { data: unknown; error: { message: string } | null };

class StaticSupabaseQuery implements PromiseLike<SupabaseResponse> {
  private readonly response: SupabaseResponse;

  constructor(response: SupabaseResponse) { this.response = response; }
  select() { return this; }
  eq() { return this; }
  not() { return this; }
  order() { return this; }
  limit() { return this; }
  maybeSingle() { return Promise.resolve(this.response); }
  then<TResult1 = SupabaseResponse, TResult2 = never>(
    onfulfilled?: ((value: SupabaseResponse) => TResult1 | PromiseLike<TResult1>) | null,
    onrejected?: ((reason: unknown) => TResult2 | PromiseLike<TResult2>) | null,
  ): PromiseLike<TResult1 | TResult2> {
    return Promise.resolve(this.response).then(onfulfilled, onrejected);
  }
}

class StaticSupabaseClient {
  private readonly responses: Record<string, SupabaseResponse[]>;

  constructor(responses: Record<string, SupabaseResponse[]>) { this.responses = responses; }
  from(table: string) {
    return new StaticSupabaseQuery(
      this.responses[table]?.shift() ?? { data: [], error: null },
    );
  }
}

test("Supabase에 live만 있어도 과거 감성·재무는 정적 데이터로 각각 폴백한다", async () => {
  const live = {
    track: "live",
    source: "newsapi_ai",
    backend: "kr-finbert",
    status: "ok",
    as_of: "2026-09-26T09:00:00+09:00",
    window_start: "2026-09-25",
    window_end: "2026-09-26",
    sentiment_mean: 0.6,
    sentiment_std: 0.1,
    article_count: 8,
    publisher_count: 3,
    fetched_count: 25,
    relevant_count: 8,
    newest_published_at: "2026-09-26T08:30:00+09:00",
    lag_minutes: 30,
    provider_total_results: 25,
    provider_returned_count: 25,
    provider_pages: 1,
    provider_truncated: false,
  };
  const client = new StaticSupabaseClient({
    news_sentiment_tracks: [{ data: [live], error: null }],
    news_sentiment_daily: [{ data: [], error: null }],
    news_articles: [{
      data: Array.from({ length: 4 }, (_, index) => ({
        news_id: `n${index}`,
        title: `대표 기사 ${index}`,
        press: "언론사",
        url: `https://example.com/${index}`,
        article_date: "2026-09-26",
        published_at: `2026-09-26T0${8 - index}:30:00+09:00`,
      })),
      error: null,
    }],
    financial_snapshots: [{ data: null, error: null }],
  });

  const insights = await loadStockInsights("005930", client as never);

  assert.equal(insights.sentiment?.days.length, 20);
  assert.equal(insights.liveSentiment?.score, 0.6);
  assert.equal(insights.sentiment?.headlines.length, 3);
  assert.equal(insights.financial?.metrics.length, 6);
  assert.equal(insights.provenance.liveSentiment.source, "NewsAPI.ai · KR-FinBERT");
  assert.equal(insights.provenance.sentiment.source, "BigKinds · KR-FinBERT · 저장된 데이터");
  const collectedAt = Date.parse("2026-09-26T09:00:00+09:00");
  assert.equal(marketSentimentView(insights, collectedAt + 73 * 3_600_000)?.basis, "historical");
  assert.deepEqual(marketSentimentView(insights, collectedAt), {
    basis: "live",
    score: 0.6,
    status: "ok",
    asOf: "2026-09-26T09:00:00+09:00",
    articleCount: 8,
    publisherCount: 3,
    headlines: insights.sentiment?.headlines,
  });
});
