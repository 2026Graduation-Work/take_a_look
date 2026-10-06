// Opt-in server-side Supabase fixture for full-period chart integration tests.
const START = Date.parse('2016-01-01T00:00:00Z');
const END = Date.parse('2026-10-04T00:00:00Z');
const daily = Array.from({ length: (END - START) / 86_400_000 + 1 }, (_, index) => ({
  sentiment_date: new Date(START + index * 86_400_000).toISOString().slice(0, 10),
  status: 'ok', sentiment_mean: index % 2 ? -0.4 : 0.8,
  sentiment_std: 0.1, article_count: index % 2 ? 2 : 8, publisher_count: 2,
})).reverse();

export function sentimentHistoryFixture(url) {
  if (process.env.TAL_SENTIMENT_E2E !== '1') return null;
  if (url.pathname.endsWith('/news_sentiment_daily')) {
    if (url.searchParams.get('track') === 'eq.live') {
      const today = new Date(Date.now() + 9 * 3_600_000).toISOString().slice(0,10);
      return [{sentiment_date:today,sentiment_mean:0.6,article_count:8}];
    }
    const offset = Number(url.searchParams.get('offset') || 0);
    const limit = Number(url.searchParams.get('limit') || 1000);
    return daily.slice(offset, offset + limit);
  }
  if (url.pathname.endsWith('/news_articles')) {
    if (url.searchParams.get('track') !== 'eq.live') return [];
    const today = new Date(Date.now() + 9 * 3_600_000).toISOString().slice(0,10);
    return Array.from({length:8}, (_,i)=>({news_id:'live-'+i,title:'네이버 뉴스 '+i,press:'언론',url:'https://news.test/live/'+i,article_date:today,published_at:null,sentiment_score:0.6}));
  }
  if (url.pathname.endsWith('/news_sentiment_tracks')) {
    const current = new Date().toISOString();
    const common = { backend: 'kr-finbert', status: 'ok', article_count: 8, publisher_count: 2,
      fetched_count: 8, relevant_count: 8, sentiment_mean: 0.6, sentiment_std: 0.1,
      newest_published_at: current, lag_minutes: 0 };
    return [
      { ...common, track: 'historical', source: 'bigkinds', as_of: '2026-10-04T23:59:59+09:00',
        window_start: '2016-01-01', window_end: '2026-10-04' },
      { ...common, track: 'live', source: 'newsapi_ai', as_of: current,
        window_start: current.slice(0, 10), window_end: current.slice(0, 10) },
    ];
  }
  return null;
}
