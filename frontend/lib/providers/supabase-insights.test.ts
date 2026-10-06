import assert from "node:assert/strict";
import { test } from "node:test";
import {
  liveArticlePeriodDays,
  loadSupabaseFinancial,
  loadSupabaseSentiment,
} from "./supabase-insights.ts";

type Response = { data: unknown; error: { message: string } | null };

class FakeQuery implements PromiseLike<Response> {
  private readonly response: Response;
  readonly operations: Array<[string, ...unknown[]]>;

  constructor(response: Response, operations: Array<[string, ...unknown[]]>) {
    this.response = response;
    this.operations = operations;
  }

  select(...args: unknown[]) { this.operations.push(["select", ...args]); return this; }
  gte(...args: unknown[]) { this.operations.push(["gte", ...args]); return this; }
  lte(...args: unknown[]) { this.operations.push(["lte", ...args]); return this; }
  in(...args: unknown[]) { this.operations.push(["in", ...args]); return this; }
  eq(...args: unknown[]) { this.operations.push(["eq", ...args]); return this; }
  not(...args: unknown[]) { this.operations.push(["not", ...args]); return this; }
  order(...args: unknown[]) { this.operations.push(["order", ...args]); return this; }
  limit(...args: unknown[]) { this.operations.push(["limit", ...args]); return this; }
  range(...args: unknown[]) { this.operations.push(["range", ...args]); return this; }
  maybeSingle() { this.operations.push(["maybeSingle"]); return Promise.resolve(this.response); }
  then<TResult1 = Response, TResult2 = never>(
    onfulfilled?: ((value: Response) => TResult1 | PromiseLike<TResult1>) | null,
    onrejected?: ((reason: unknown) => TResult2 | PromiseLike<TResult2>) | null,
  ): PromiseLike<TResult1 | TResult2> {
    return Promise.resolve(this.response).then(onfulfilled, onrejected);
  }
}

class FakeClient {
  readonly operations: Record<string, Array<[string, ...unknown[]]>> = {};
  private readonly responses: Record<string, Response[]>;

  constructor(responses: Record<string, Response[]>) {
    this.responses = responses;
  }

  from(table: string) {
    const operations = (this.operations[table] ??= []);
    const response = this.responses[table]?.shift() ?? { data: [], error: null };
    return new FakeQuery(response, operations);
  }
}

const trackRows = [
  {
    stock_code: "005930",
    track: "historical",
    source: "bigkinds",
    backend: "kr-finbert",
    status: "ok",
    as_of: "2025-12-02T23:59:59+09:00",
    window_start: "2025-11-13",
    window_end: "2025-12-02",
    sentiment_mean: 0.2,
    sentiment_std: 0.3,
    article_count: 40,
    publisher_count: 4,
    fetched_count: 50,
    relevant_count: 40,
    newest_published_at: null,
    lag_minutes: null,
    provider_total_results: null,
    provider_returned_count: null,
    provider_pages: null,
    provider_truncated: false,
  },
  {
    stock_code: "005930",
    track: "live",
    source: "newsapi_ai",
    backend: "kr-finbert",
    status: "partial",
    as_of: "2026-09-26T09:00:00+09:00",
    window_start: "2026-09-25",
    window_end: "2026-09-26",
    sentiment_mean: 0.45,
    sentiment_std: 0.2,
    article_count: 12,
    publisher_count: 5,
    fetched_count: 100,
    relevant_count: 12,
    newest_published_at: "2026-09-26T08:40:00+09:00",
    lag_minutes: 20,
    provider_total_results: 120,
    provider_returned_count: 100,
    provider_pages: 2,
    provider_truncated: true,
  },
];

test("Supabase 감성은 전체 과거 일별값과 live 요약·대표 기사 3건을 분리한다", async () => {
  const daily = Array.from({ length: 22 }, (_, index) => ({
    sentiment_date: `2025-11-${String(index + 1).padStart(2, "0")}`,
    status: "ok",
    sentiment_mean: index === 0 ? null : index / 100,
    sentiment_std: 0.1,
    article_count: index + 1,
    publisher_count: 2,
  })).reverse();
  const articles = Array.from({ length: 4 }, (_, index) => ({
    news_id: `n${index}`,
    title: `기사 ${index}`,
    press: "언론사",
    article_date: `2026-09-${26 - index}`,
    published_at: `2026-09-${26 - index}T08:00:00+09:00`,
  }));
  const client = new FakeClient({
    news_sentiment_tracks: [{ data: trackRows, error: null }],
    news_sentiment_daily: [{ data: daily, error: null }],
    news_articles: [{ data: articles, error: null }],
  });

  const result = await loadSupabaseSentiment("005930", client as never);

  assert.equal(result.historical?.days.length, 21);
  assert.equal(result.historical?.days[0].date, "2025-11-02");
  assert.equal(result.historical?.days.at(-1)?.date, "2025-11-22");
  assert.deepEqual(result.live, {
    periodDays: [],
    score: 0.45,
    scoreStd: 0.2,
    articleCount: 12,
    publisherCount: 5,
    status: "partial",
    asOf: "2026-09-26T09:00:00+09:00",
    windowStart: "2026-09-25",
    windowEnd: "2026-09-26",
    coverage: {
      fetched_count: 100,
      relevant_count: 12,
      publisher_count: 5,
      newest_published_at: "2026-09-26T08:40:00+09:00",
      lag_minutes: 20,
      provider_total_results: 120,
      provider_returned_count: 100,
      provider_pages: 2,
      provider_truncated: true,
    },
  });
  assert.deepEqual(result.headlines.map(({ title }) => title), ["기사 0", "기사 1", "기사 2"]);
  assert.ok(!client.operations.news_sentiment_daily.some(([name]) => name === "limit"));
  assert.ok(client.operations.news_articles.some(([name, count]) => name === "limit" && count === 25));
  assert.ok(client.operations.news_articles.some(
    ([name, columns]) => name === "select" && String(columns).includes("sentiment_score"),
  ));
  assert.deepEqual(
    client.operations.news_articles.filter(([name]) => name === "order"),
    [
      ["order", "published_at", { ascending: false, nullsFirst: false }],
      ["order", "news_id", { ascending: true }],
    ],
  );
});

test("과거 감성 일별값이 1000건을 넘으면 다음 페이지까지 읽는다", async () => {
  const firstPage = Array.from({ length: 1000 }, (_, index) => ({
    sentiment_date: new Date(Date.UTC(2020, 0, index + 1)).toISOString().slice(0, 10),
    sentiment_mean: 0.2,
    article_count: 1,
  })).reverse();
  const olderPage = [{
    sentiment_date: "2019-12-31",
    sentiment_mean: -0.1,
    article_count: 2,
  }];
  const client = new FakeClient({
    news_sentiment_tracks: [{ data: trackRows, error: null }],
    news_sentiment_daily: [
      { data: firstPage, error: null },
      { data: olderPage, error: null },
    ],
    news_articles: [{ data: [], error: null }],
  });

  const result = await loadSupabaseSentiment("005930", client as never);

  assert.equal(result.historical?.days.length, 1001);
  assert.equal(result.historical?.days[0].date, "2019-12-31");
  assert.deepEqual(
    client.operations.news_sentiment_daily.filter(([name]) => name === "range"),
    [["range", 0, 999], ["range", 1000, 1999]],
  );
});

test("대표 기사는 종목명 제목·전체 감성지수와의 거리·사건과 언론사를 우선한다", async () => {
  const articles = [
    {
      news_id: "indirect-newest",
      title: "아이폰 이어 갤럭시까지 가격 역주행 조심",
      press: "it.donga.com",
      url: "https://it.donga.com/1",
      event_id: "event-indirect",
      article_date: "2026-09-28",
      published_at: "2026-09-28T11:00:00+09:00",
    },
    {
      news_id: "direct-a",
      title: "삼성전자, 삼성 AI 구독 새단장",
      press: "GS칼텍스, 인도네시아서 바이오원료 생산 개시… 원료 확보부터 판매까지",
      url: "https://www.newsis.com/view/1",
      event_id: "event-subscription",
      sentiment_score: 0.46,
      article_date: "2026-09-28",
      published_at: "2026-09-28T10:30:00+09:00",
    },
    {
      news_id: "direct-a-duplicate",
      title: "삼성전자 AI 구독 새단장…맞춤 케어 강화",
      press: "서울신문",
      url: "https://seoul.co.kr/2",
      event_id: "event-subscription",
      sentiment_score: 0.44,
      article_date: "2026-09-28",
      published_at: "2026-09-28T10:20:00+09:00",
    },
    {
      news_id: "broken",
      title: "��� 삼성전자 기사",
      press: "�����",
      url: "https://broken.example/3",
      event_id: "event-broken",
      sentiment_score: 0.45,
      article_date: "2026-09-28",
      published_at: "2026-09-28T10:10:00+09:00",
    },
    {
      news_id: "direct-b",
      title: "삼성전자 파운드리 신규 수주",
      press: "한국경제",
      url: "https://hankyung.com/4",
      event_id: "event-foundry",
      sentiment_score: 0.9,
      article_date: "2026-09-28",
      published_at: "2026-09-28T10:00:00+09:00",
    },
    {
      news_id: "direct-c",
      title: "삼성전자 반도체 생산량 확대",
      press: "한국경제",
      url: "https://hankyung.com/5",
      event_id: "event-production",
      sentiment_score: -0.7,
      article_date: "2026-09-28",
      published_at: "2026-09-28T09:50:00+09:00",
    },
    {
      news_id: "direct-d",
      title: "삼성전자 신규 메모리 공개",
      press: "매일경제",
      url: "https://mk.co.kr/6",
      event_id: "event-memory",
      sentiment_score: 0.4,
      article_date: "2026-09-28",
      published_at: "2026-09-28T09:40:00+09:00",
    },
  ];
  const client = new FakeClient({
    news_sentiment_tracks: [{ data: trackRows, error: null }],
    news_sentiment_daily: [{ data: [], error: null }],
    news_articles: [{ data: articles, error: null }],
  });

  const result = await loadSupabaseSentiment("005930", client as never);

  assert.deepEqual(result.headlines.map(({ title }) => title), [
    "삼성전자, 삼성 AI 구독 새단장",
    "삼성전자 신규 메모리 공개",
    "삼성전자 파운드리 신규 수주",
  ]);
  assert.equal(result.headlines[0].press, "뉴시스");
  assert.ok(result.headlines.every(({ title }) => !title.includes("�")));
});

test("직접 관련 기사가 3건 이상이면 언론사가 겹쳐도 간접 기사로 대체하지 않는다", async () => {
  const articles = [
    {
      news_id: "direct-1",
      title: "삼성전자 반도체 투자 확대",
      press: "한국경제",
      url: "https://hankyung.com/1",
      event_id: "direct-event-1",
      article_date: "2026-09-28",
      published_at: "2026-09-28T11:00:00+09:00",
    },
    {
      news_id: "direct-2",
      title: "삼성전자 파운드리 신규 수주",
      press: "한국경제",
      url: "https://hankyung.com/2",
      event_id: "direct-event-2",
      article_date: "2026-09-28",
      published_at: "2026-09-28T10:00:00+09:00",
    },
    {
      news_id: "direct-3",
      title: "삼성전자 신규 메모리 공개",
      press: "한국경제",
      url: "https://hankyung.com/3",
      event_id: "direct-event-3",
      article_date: "2026-09-28",
      published_at: "2026-09-28T09:00:00+09:00",
    },
    {
      news_id: "indirect-1",
      title: "갤럭시 최신 동향",
      press: "매일경제",
      url: "https://mk.co.kr/4",
      event_id: "indirect-event-1",
      article_date: "2026-09-28",
      published_at: "2026-09-28T08:00:00+09:00",
    },
  ];
  const client = new FakeClient({
    news_sentiment_tracks: [{ data: trackRows, error: null }],
    news_sentiment_daily: [{ data: [], error: null }],
    news_articles: [{ data: articles, error: null }],
  });

  const result = await loadSupabaseSentiment("005930", client as never);

  assert.deepEqual(result.headlines.map(({ title }) => title), [
    "삼성전자 반도체 투자 확대",
    "삼성전자 파운드리 신규 수주",
    "삼성전자 신규 메모리 공개",
  ]);
  assert.ok(result.headlines.every(({ press }) => press === "한국경제"));
});

test("기존 DB의 검증된 도메인은 화면에서 언론사명으로 표시한다", async () => {
  const articles = [
    ["m.segyebiz.com", "https://m.segyebiz.com/1"],
    ["ajunews.com", "https://www.ajunews.com/2"],
    ["businesspost.co.kr", "https://www.businesspost.co.kr/3"],
  ].map(([press, url], index) => ({
    news_id: `publisher-${index}`,
    title: `삼성전자 관련 기사 ${index}`,
    press,
    url,
    event_id: `publisher-event-${index}`,
    sentiment_score: 0.45,
    article_date: "2026-09-28",
    published_at: `2026-09-28T0${9 - index}:00:00+09:00`,
  }));
  const client = new FakeClient({
    news_sentiment_tracks: [{ data: trackRows, error: null }],
    news_sentiment_daily: [{ data: [], error: null }],
    news_articles: [{ data: articles, error: null }],
  });

  const result = await loadSupabaseSentiment("005930", client as never);

  assert.deepEqual(result.headlines.map(({ press }) => press), ["세계비즈", "아주경제", "비즈니스포스트"]);
});

test("도메인으로 검증할 수 없는 언론사 값은 본문 대신 미상으로 표시한다", async () => {
  const client = new FakeClient({
    news_sentiment_tracks: [{ data: trackRows, error: null }],
    news_sentiment_daily: [{ data: [], error: null }],
    news_articles: [{ data: [{
      news_id: "missing-domain",
      title: "삼성전자 실적 개선",
      press: "원료 확보부터 판매까지",
      url: "",
      event_id: "event-missing-domain",
      article_date: "2026-09-28",
      published_at: "2026-09-28T11:00:00+09:00",
    }], error: null }],
  });

  const result = await loadSupabaseSentiment("005930", client as never);

  assert.equal(result.headlines[0].press, "언론사 미상");
});

test("기사 URL이 없어도 수집 단계에서 검증한 언론사 도메인은 표시한다", async () => {
  const client = new FakeClient({
    news_sentiment_tracks: [{ data: trackRows, error: null }],
    news_sentiment_daily: [{ data: [], error: null }],
    news_articles: [{ data: [{
      news_id: "source-domain-only",
      title: "삼성전자 실적 개선",
      press: "hankyung.com",
      url: "",
      event_id: "event-source-domain-only",
      article_date: "2026-09-28",
      published_at: "2026-09-28T11:00:00+09:00",
    }], error: null }],
  });

  const result = await loadSupabaseSentiment("005930", client as never);

  assert.equal(result.headlines[0].press, "한국경제");
});

test("Supabase 재무는 최신 스냅샷과 여섯 지표의 근거를 화면 계약으로 바꾼다", async () => {
  const snapshot = {
    id: "snapshot-id",
    fiscal_year: 2024,
    statement: "CFS",
    receipt_no: "20250311001085",
    filed_at: "2025-03-11",
    shares_basis: "2024-12-31 common_shares",
    price_as_of: "2025-12-30",
  };
  const keys = ["per", "pbr", "roe", "operating_margin", "debt_ratio", "revenue_growth"];
  const metrics = keys.map((metric_key, index) => ({
    metric_key,
    value: index + 1,
    unit: index < 2 ? "multiple" : "percent",
    basis: `${metric_key} 근거`,
    note: null,
  }));
  const client = new FakeClient({
    financial_snapshots: [{ data: snapshot, error: null }],
    financial_metrics: [{ data: metrics, error: null }],
  });

  const result = await loadSupabaseFinancial("005930", client as never);

  assert.match(result?.period ?? "", /2024 사업연도 · 연결재무제표.*2025-03-11 공시/);
  assert.deepEqual(result?.metrics.map(({ key, basis }) => [key, basis]),
    keys.map((key) => [key, `${key} 근거`]));
});

test("Supabase 조회 오류는 호출자에게 전달해 섹션별 폴백을 가능하게 한다", async () => {
  const client = new FakeClient({
    news_sentiment_tracks: [{ data: null, error: { message: "unavailable" } }],
  });

  await assert.rejects(() => loadSupabaseSentiment("005930", client as never), /unavailable/);
});

test("Live 기간 집계는 KST 기사 날짜로 나누고 ID·URL·제목 중복을 제외한다", () => {
  const historical=[{news_id:"old",title:"공통 뉴스",press:"언론",url:"https://news.test/a",article_date:"2025-12-31",published_at:null,sentiment_score:0.2}];
  const common={press:"언론",published_at:null};
  const articles=[
    {...common,news_id:"live-duplicate",title:"공통 뉴스",url:"https://news.test/a?utm_source=live",article_date:"2025-12-31",sentiment_score:0.8},
    {...common,news_id:"b",title:"이전 해 뉴스",url:"https://news.test/b",article_date:"2025-12-31",sentiment_score:-0.4},
    {...common,news_id:"b",title:"이전 해 뉴스",url:"https://news.test/b",article_date:"2025-12-31",sentiment_score:-0.4},
    {...common,news_id:"c",title:"새해 뉴스",url:"https://news.test/c",article_date:"2025-12-31",published_at:"2025-12-31T16:00:00Z",sentiment_score:1},
  ];
  assert.deepEqual(liveArticlePeriodDays(articles,historical),[
    {date:"2025-12-31",score:-0.4,articleCount:1},
    {date:"2026-01-01",score:1,articleCount:1},
  ]);
});

test("월·연에 쓰는 Live 일별 점수는 DB 결과를 그대로 재사용한다", async () => {
  const client=new FakeClient({
    news_sentiment_tracks:[{data:trackRows,error:null}],
    news_sentiment_daily:[{data:[],error:null},{data:[{sentiment_date:"2026-09-25",sentiment_mean:0.3,article_count:9},{sentiment_date:"2026-09-26",sentiment_mean:-0.2,article_count:3},{sentiment_date:"2026-09-01",sentiment_mean:1,article_count:99}],error:null}],
    news_articles:[{data:[],error:null}],
  });
  const result=await loadSupabaseSentiment("005930",client as never);
  assert.deepEqual(result.live?.periodDays,[{date:"2026-09-25",score:0.3,articleCount:9},{date:"2026-09-26",score:-0.2,articleCount:3}]);
  assert.equal(client.operations.news_articles.filter(([op])=>op==="select").length,1);
});

test("날짜만 저장된 Live 창도 overlap 기사 집계는 기준시각 직전 24시간으로 제한한다", async () => {
  const article=(id:string,published_at:string)=>({news_id:id,title:id,press:"언론",url:"https://news.test/"+id,article_date:"2026-09-25",published_at,sentiment_score:0.5});
  const client=new FakeClient({
    news_sentiment_tracks:[{data:trackRows,error:null}],
    news_sentiment_daily:[{data:[{sentiment_date:"2026-09-25",sentiment_mean:0.2,article_count:2}],error:null},{data:[{sentiment_date:"2026-09-25",sentiment_mean:0.5,article_count:1}],error:null}],
    news_articles:[{data:[],error:null},{data:[article("old","2026-09-25T08:00:00+09:00"),article("current","2026-09-25T12:00:00+09:00")],error:null},{data:[],error:null}],
  });
  const result=await loadSupabaseSentiment("005930",client as never);
  assert.deepEqual(result.live?.periodDays,[{date:"2026-09-25",score:0.5,articleCount:1}]);
});
