import assert from "node:assert/strict";
import { SUPPLY_SNAPSHOT } from "./demo-snapshot.ts";
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
  aggregateSentimentPeriods,
  sentimentDaysIncludingLive,
  contributionProvider,
  loadStockInsights,
  marketSentimentView,
  todayLiveSentimentView,
  sentimentProvider,
  toNudgeMarket,
} from "./index.ts";

test("감성 기간 집계: 일별은 유지하고 월·년별은 기사 수 가중평균을 쓴다", () => {
  const days = [
    { date: "2026-01-02", score: 0.8, articleCount: 8 },
    { date: "2026-01-03", score: -0.4, articleCount: 2 },
    { date: "2026-02-01", score: -0.5, articleCount: 5 },
    { date: "2026-02-02", score: 0.9, articleCount: 0 },
  ];

  assert.deepEqual(aggregateSentimentPeriods(days, "day"), days);
  assert.deepEqual(aggregateSentimentPeriods(days, "month"), [
    { date: "2026-01", score: 0.56, articleCount: 10 },
    { date: "2026-02", score: -0.5, articleCount: 5 },
  ]);
  const yearly = aggregateSentimentPeriods(days, "year");
  assert.equal(yearly[0].date, "2026");
  assert.equal(yearly[0].articleCount, 15);
  assert.ok(Math.abs(yearly[0].score - (3.1 / 15)) < 1e-12);
});

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

  });
}

test("대상 외 종목은 null", async () => {
  const { supply, sentiment, contributions, financial } = await loadStockInsights("000660");
  assert.deepEqual(
    { supply, sentiment, contributions, financial },
    { supply: null, sentiment: null, contributions: null, financial: null },
  );
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


function minjiWith(overrides: Record<string, number>): StyleAxes {
  return {
    ...investorStyleAxes,
    axes: investorStyleAxes.axes.map((axis) =>
      axis.axis_id in overrides ? { ...axis, ratio: overrides[axis.axis_id] } : axis,
    ),
  };
}

async function samsungNudges(styleAxes: StyleAxes) {
  // 1년 변동성·백분위는 종목 마스터 값(2026-10-06 운영 실측)을 넣는다
  const detail = { ...stockDetails["005930"], volatilityAnnual: 0.8681, volatilityPercentile: 0.8518 };
  // 수급은 DB에서만 오므로(0013), 넛지 규칙 검사에는 저장된 실데이터 20영업일을 직접 넣는다
  const insights = { ...(await loadStockInsights("005930")), supply: SUPPLY_SNAPSHOT["005930"] };
  const market = toNudgeMarket(detail, insights, portfolioHoldings);
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
  in() { return this; }
  gte() { return this; }
  lte() { return this; }
  not() { return this; }
  order() { return this; }
  limit() { return this; }
  range() { return this; }
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

test("Supabase에 live만 있으면 과거 감성은 정적 데이터로 폴백하고, 재무는 대체값 없이 비운다", async () => {
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
  assert.equal(insights.financial, null); // 고정 재무 대체값은 두지 않는다(최신 정기보고서만)
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

test("오늘 Live 표시: KST 날짜가 바뀌면 최근 Live도 오늘 점으로 표시하지 않는다", async () => {
  const base = await loadStockInsights("005930", null);
  const insights = { ...base, liveSentiment: {
    score: 0.6, scoreStd: 0.1, articleCount: 8, publisherCount: 3, status: "ok" as const,
    asOf: "2026-10-05T14:59:00Z", windowStart: "2026-10-04", windowEnd: "2026-10-05",
    coverage: { fetched_count: 8, relevant_count: 8, publisher_count: 3, newest_published_at: null, lag_minutes: null },
  } };
  assert.equal(todayLiveSentimentView(insights, Date.parse("2026-10-05T14:59:30Z"))?.score, 0.6);
  assert.equal(todayLiveSentimentView(insights, Date.parse("2026-10-05T15:00:00Z")), null);
  assert.equal(todayLiveSentimentView(insights, Date.parse("2026-10-05T14:58:00Z")), null);
});

 test("과거 일별 뒤에 Live 일별을 이어 붙이고 월·연은 기사 수로 합치며 원본을 바꾸지 않는다", async () => {
  const base = await loadStockInsights("005930", null);
  const insights = { ...base, sentiment: { ...base.sentiment!, days: [{date:"2025-12-31",score:0.2,articleCount:10}] },
    liveSentiment: {score:0.1,scoreStd:0,articleCount:3,publisherCount:1,status:"ok" as const,
      asOf:"2026-01-01T09:00:00+09:00",windowStart:"",windowEnd:"",coverage:base.sentiment!.coverage!,
      periodDays:[{date:"2025-12-31",score:-0.4,articleCount:2},{date:"2026-01-01",score:1,articleCount:1}]}};
  const days = sentimentDaysIncludingLive(insights);
  const months = aggregateSentimentPeriods(days,"month");
  assert.equal(months[0].articleCount,12);
  assert.ok(Math.abs(months[0].score-0.1)<1e-12);
  assert.deepEqual(months[1],{date:"2026-01",score:1,articleCount:1});
  assert.equal(aggregateSentimentPeriods(days,"year")[0].date,"2025");
  assert.equal(insights.sentiment.days[0].articleCount,10);
  assert.equal(days.length,3);
});
