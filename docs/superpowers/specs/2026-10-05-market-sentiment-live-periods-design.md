# Market Sentiment Live and Period Views Design

## Purpose

Make the stock-detail market-sentiment tab useful as an evidence view: show
BigKinds historical sentiment across daily, monthly, and yearly periods, and
make the current NewsAPI.ai result visibly distinct without mixing sources.
Extend the same flow from four stocks to NAVER and EcoPro BM.

## Scope

- Six stocks: Samsung Electronics (`005930`), Hyundai Motor (`005380`),
  Kakao (`035720`), Celltrion (`068270`), NAVER (`035420`), and EcoPro BM
  (`247540`).
- Historical BigKinds news from 2026-01-01 through 2026-10-04 is imported
  for every stock. Existing dates are updated by idempotent upsert.
- Existing Live rows are reset only at the row level; no Supabase table,
  policy, index, or schema contract is dropped or recreated.
- The live collector then starts a clean NewsAPI.ai series from the reset day.

## Data model and provenance

`historical` and `live` remain separate `track` values.

- `historical` is the chart baseline. Its daily rows come from BigKinds and
  KR-FinBERT.
- `live` is the current 24-hour observation. It comes from NewsAPI.ai and
  KR-FinBERT. It is never inserted into historical aggregates.
- Daily points use the stored daily mean and relevant-article count.
- Monthly and yearly points are deterministic article-count weighted means:

  `sum(sentiment_mean * article_count) / sum(article_count)`.

  Dates with no usable sentiment mean or zero relevant articles do not add a
  score or a weight. This avoids treating an article-free day as neutral.

## UI

The existing Market panel receives a nested `일별 / 월별 / 연별` segmented
tab. It retains the existing chart question and y-axis (-1 to +1), rather than
presenting these aggregates as price values.

- The chosen historical period is drawn as the primary neutral chart line.
- If a valid live record is current, its score appears at the right edge as a
  slightly larger hollow circle on the same line color. A short adjacent
  label identifies it as `오늘 Live` with its collection time and source.
- No new semantic color is added. The marker, label, and existing source chip
  keep the interface consistent with `frontend/DESIGN.md`.
- Tooltips identify the period, weighted score, and relevant article count.
- Representative news shows headline and publisher only. Stock-price sources
  such as NAVER or KRX are not shown in that article block; the market panel's
  own source chips remain responsible for data provenance.

## Persistence and operations

Add an operator-only manual workflow mode that, using the existing trusted
Supabase credential, removes six-stock `live` rows from all three news tables
(`news_sentiment_tracks`, `news_sentiment_daily`, `news_articles`). It does
not touch `historical` rows. The same workflow then runs the normal six-stock
live collection, so the fresh current observation is available immediately.

Add a backfill command for BigKinds workbooks that builds and persists the
historical tracks for all six targets. It uses the existing deterministic
collector and `persist_news_track` upsert behavior. No schema migration is
required.

## Six-stock extension

Register NAVER and EcoPro BM in the UI stock catalog and Supabase seed/data
setup, then include both in the scheduled NewsAPI.ai workflow and the
historical backfill target list. Their detail pages use the same unavailable
states for evidence categories that do not yet have validated inputs; no
model signal, recommendation, or financial value is invented.

## Testing

- Provider tests cover daily, monthly, and yearly article-count weighted
  aggregation; empty dates; and a current live marker that does not alter the
  historical aggregation.
- Supabase adapter tests assert complete historical retrieval rather than the
  old 20-row limit and six-stock representative-title matching.
- Backend tests cover six-target reset scope and the historical workbook
  backfill command without external credentials.
- Component/e2e tests cover nested period tabs, selected-state accessibility,
  and the live marker/label.

## Non-goals

- No prediction price curve, trading instruction, or automatic trading.
- No mixing NewsAPI.ai live results into BigKinds historical values.
- No destructive table recreation or schema change.
