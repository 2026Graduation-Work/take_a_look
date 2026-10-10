# News and Financial Supabase Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the four supported stocks' news and DART analysis in Supabase, refresh live news at 09:00 KST on weekdays, and make the stock UI prefer Supabase while retaining the existing static fallback.

**Architecture:** A focused Python PostgREST adapter maps existing track JSON into the five tables introduced by migration 0005. GitHub Actions invokes a four-stock, per-stock NewsAPI.ai collection command, while the Next.js provider layer composes historical, live, article, and financial rows into the existing UI types and falls back to committed fixtures when Supabase is unavailable.

**Tech Stack:** Python 3.12, requests, pytest, KR-FinBERT/transformers, GitHub Actions, Supabase PostgREST/RLS, Next.js, TypeScript, `@supabase/supabase-js`, Node test runner.

**Spec:** `docs/superpowers/specs/2026-09-26-text-supabase-live-sync-design.md`

## Global Constraints

- Supported stocks are exactly `005930`, `005380`, `035720`, and `068270`.
- The scheduled workflow runs at `0 0 * * 1-5` (09:00 KST on weekdays) and also supports `workflow_dispatch`.
- NewsAPI.ai is called once per stock, with at most 100 candidates per call; no OR query across stocks and no second page.
- Every relevant candidate in the provider response is scored; article count is not arbitrarily capped at 25.
- Scheduled persistence requires the `kr-finbert` backend and never mixes lexicon fallback scores into Supabase.
- The UI shows exactly up to three newest live evidence articles.
- Article body, summary, and content are never persisted.
- Backend secrets are `NEWSAPI_AI_KEY`, `SUPABASE_URL`, and `SUPABASE_SECRET_KEY`; no secret is committed or exposed through `NEXT_PUBLIC_*`.
- Browser clients remain read-only under migration 0005 RLS.
- Empty or failed collection never overwrites the last successful track.
- Existing unrelated untracked paths `.pnpm-store/`, `artifacts/`, and `supabase/.temp/` remain untouched and uncommitted.

## Review Focus

- A provider response with more than 100 matches must persist `partial` instead of presenting the sample as complete; Task 2 adds this assertion.
- An article exactly on the 24-hour KST boundary must be included once, while an older article is excluded; Task 2 adds boundary tests.
- A run where one stock fails after other stocks succeed must preserve successful writes and exit non-zero; Task 4 adds the partial-success test.
- A financial snapshot upsert returning no UUID must not write orphan metrics; Task 3 adds the response-contract test.
- A Supabase response with live data but no historical or financial rows must fall back per section rather than discard all valid live data; Task 6 adds mixed-source tests.

---

### Task 1: KR-FinBERT Batch Scoring and Strict Backend Mode

**Files:**
- Modify: `backend/analysis/text/value_pipeline/sentiment.py`
- Modify: `backend/analysis/text/value_pipeline/config.py`
- Modify: `backend/analysis/text/tests/test_value_pipeline.py`

**Interfaces:**
- Produces: `score_texts(texts: list[str], *, require_finbert: bool = False, batch_size: int = 16) -> tuple[list[float], str]`
- Produces: `SentimentBackendError`, raised only when strict mode is requested and KR-FinBERT cannot load or infer.
- Consumes: existing `_load_finbert`, `_lexicon_score`, and `SETTINGS.finbert_model`.

- [ ] **Step 1: Write failing batch and strict-mode tests**

Add tests proving one classifier call receives the full list with `batch_size=16`, output order is preserved, and `require_finbert=True` raises `SentimentBackendError` instead of using the lexicon when the model is unavailable.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `../../../.venv/bin/pytest tests/test_value_pipeline.py -k "batch or require_finbert" -v`

Expected: FAIL because the new keyword arguments and exception do not exist.

- [ ] **Step 3: Implement batch normalization without changing score semantics**

Update `score_texts` with the exact signature above. Normalize both single-text and list pipeline result shapes into one score per input, clamp each score to `[-1, 1]`, and preserve the current lexicon behavior unless strict mode is enabled.

- [ ] **Step 4: Run sentiment and full text tests**

Run: `../../../.venv/bin/pytest tests/test_value_pipeline.py -v`

Run: `../../../.venv/bin/pytest -q`

Expected: all text tests PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add backend/analysis/text/value_pipeline/sentiment.py backend/analysis/text/value_pipeline/config.py backend/analysis/text/tests/test_value_pipeline.py
git commit -m "perf(text): batch FinBERT news scoring"
```

### Task 2: Per-Stock 24-Hour Live News Collection

**Files:**
- Modify: `backend/analysis/text/value_pipeline/news_tracks.py`
- Modify: `backend/analysis/text/value_pipeline/news_run.py`
- Modify: `backend/analysis/text/tests/test_news_tracks.py`
- Modify: `backend/analysis/text/tests/test_newsapi_ai.py`

**Interfaces:**
- Produces: `run_live_cycle(targets, *, fetcher, as_of=None, page_size=100, require_finbert=False) -> dict[str, dict[str, Any]]`, with one fetcher call per target.
- Produces: every live track contains a generic `window` object with `start`, `end`, `status`, `sentiment_mean`, `sentiment_std`, `article_count`, and `publisher_count` for the exact preceding 24 hours.
- Consumes: Task 1 `score_texts(..., require_finbert=...)`.

- [ ] **Step 1: Replace the combined-call expectation with per-stock failing tests**

Assert four targets produce four fetcher calls, each call receives exactly one company keyword, and each request retains `page_size=100`.

- [ ] **Step 2: Add failing 24-hour boundary and full-relevant-set tests**

Use a fixed KST `as_of`; assert an article exactly at `as_of - 24h` is included, one second older is excluded, all remaining relevant articles are scored, and `articles` contains no body/summary/content field.

- [ ] **Step 3: Add the truncation Review Focus test**

Return provider metadata with `total_results=101`, `returned_count=100`, `pages=2`, `truncated=True`; assert track status is `partial` and the four coverage fields are preserved.

- [ ] **Step 4: Run focused tests and verify RED**

Run: `../../../.venv/bin/pytest tests/test_news_tracks.py tests/test_newsapi_ai.py -v`

Expected: FAIL on the old single combined request and seven-day window behavior.

- [ ] **Step 5: Implement per-stock collection and exact local time filtering**

Keep the provider request date range broad enough to cover the boundary, filter with timezone-aware `published_at`, add the live `window`, and pass strict FinBERT mode from CLI to the scorer. Do not remove existing historical behavior.

- [ ] **Step 6: Run focused and full text tests**

Run: `../../../.venv/bin/pytest tests/test_news_tracks.py tests/test_newsapi_ai.py -v`

Run: `../../../.venv/bin/pytest -q`

Expected: all tests PASS.

- [ ] **Step 7: Commit Task 2**

```bash
git add backend/analysis/text/value_pipeline/news_tracks.py backend/analysis/text/value_pipeline/news_run.py backend/analysis/text/tests/test_news_tracks.py backend/analysis/text/tests/test_newsapi_ai.py
git commit -m "feat(text): collect live news per stock"
```

### Task 3: Supabase PostgREST Persistence Adapter

**Files:**
- Create: `backend/analysis/text/value_pipeline/supabase_store.py`
- Create: `backend/analysis/text/tests/test_supabase_store.py`
- Modify: `backend/analysis/text/value_pipeline/config.py`

**Interfaces:**
- Produces: `SupabaseRestClient.from_env(session=requests) -> SupabaseRestClient`.
- Produces: `persist_news_track(client: SupabaseRestClient, track: Mapping[str, Any]) -> None`.
- Produces: `persist_financial_track(client: SupabaseRestClient, track: Mapping[str, Any]) -> str`, returning the snapshot UUID.
- Produces: `SupabaseConfigurationError` and `SupabaseWriteError` with sanitized messages.
- Consumes: migration 0005 table and conflict-key contracts.

- [ ] **Step 1: Write failing configuration and HTTP contract tests**

Assert missing URL/key fails before HTTP, URL normalization produces `/rest/v1/<table>`, headers contain `apikey`, bearer authorization, JSON content type, and `Prefer: resolution=merge-duplicates,return=representation` where a returned row is required.

- [ ] **Step 2: Write failing news mapping tests**

Given one live track fixture, assert exact rows for `news_sentiment_tracks`, `news_sentiment_daily`, and `news_articles`; assert forbidden body fields never appear and exact `on_conflict` values match migration 0005.

- [ ] **Step 3: Write failing financial mapping and missing-UUID tests**

Assert the snapshot is upserted first, its returned UUID becomes every metric's `snapshot_id`, six metrics are written, and an empty representation raises without sending metrics.

- [ ] **Step 4: Run the new test module and verify RED**

Run: `../../../.venv/bin/pytest tests/test_supabase_store.py -v`

Expected: ERROR because `supabase_store` does not exist.

- [ ] **Step 5: Implement the smallest REST client and deterministic mappers**

Read `SUPABASE_SECRET_KEY`, with `SUPABASE_SERVICE_ROLE_KEY` only as a compatibility fallback. Use existing `requests`; do not add `supabase-py`. Reject non-2xx responses, invalid JSON, invalid article dates, `error` tracks, and empty/lexicon news tracks.

- [ ] **Step 6: Run focused and full text tests**

Run: `../../../.venv/bin/pytest tests/test_supabase_store.py -v`

Run: `../../../.venv/bin/pytest -q`

Expected: all tests PASS.

- [ ] **Step 7: Commit Task 3**

```bash
git add backend/analysis/text/value_pipeline/supabase_store.py backend/analysis/text/value_pipeline/config.py backend/analysis/text/tests/test_supabase_store.py
git commit -m "feat(text): persist analysis tracks to Supabase"
```

### Task 4: Sync CLI, Backfill, and Failure Semantics

**Files:**
- Create: `backend/analysis/text/value_pipeline/supabase_sync.py`
- Create: `backend/analysis/text/tests/test_supabase_sync.py`
- Modify: `backend/analysis/text/README.md`
- Modify: `.env.example`

**Interfaces:**
- Produces CLI subcommands:
  - `live --target TICKER:COMPANY` (repeatable; requires strict FinBERT)
  - `backfill-news PATH...`
  - `backfill-financial PATH...`
- Produces: `run_live_sync(targets, *, client, fetcher, as_of=None) -> SyncResult` with succeeded tickers and per-ticker failures.
- Consumes: Task 2 `run_live_cycle` and Task 3 persistence functions.

- [ ] **Step 1: Write failing CLI parsing and four-stock tests**

Assert the supported default target set is the exact four codes/names and explicit `--target` values remain repeatable for testing.

- [ ] **Step 2: Write failing file backfill tests**

Use temporary historical and financial JSON files; assert each is routed to the correct Task 3 persistence function and invalid tracks fail before a write.

- [ ] **Step 3: Add the partial-success Review Focus test**

Make the second stock fail while the others succeed; assert three successful writes remain, all four were attempted, the result records the failed ticker, and CLI exit code is non-zero.

- [ ] **Step 4: Run the new test module and verify RED**

Run: `../../../.venv/bin/pytest tests/test_supabase_sync.py -v`

Expected: ERROR because `supabase_sync` does not exist.

- [ ] **Step 5: Implement orchestration and documentation**

Load secrets only at execution time, never print them, produce one concise status line per ticker, and document the three commands plus the required backend environment variables. Update root `.env.example` only with blank placeholders.

- [ ] **Step 6: Run focused and full text tests plus lint**

Run: `../../../.venv/bin/pytest tests/test_supabase_sync.py -v`

Run: `../../../.venv/bin/pytest -q`

Run from repository root: `.venv/bin/ruff check backend/analysis/text/`

Expected: all commands PASS.

- [ ] **Step 7: Commit Task 4**

```bash
git add .env.example backend/analysis/text/README.md backend/analysis/text/value_pipeline/supabase_sync.py backend/analysis/text/tests/test_supabase_sync.py
git commit -m "feat(text): add Supabase sync commands"
```

### Task 5: Scheduled GitHub Actions Workflow

**Files:**
- Create: `.github/workflows/news-supabase-sync.yml`
- Modify: `backend/analysis/text/README.md`

**Interfaces:**
- Produces: weekday 09:00 KST scheduled and manual workflow.
- Consumes: Task 4 `python -m value_pipeline.supabase_sync live` and repository secrets.

- [ ] **Step 1: Add a failing workflow contract test**

Create `backend/analysis/text/tests/test_news_sync_workflow.py` that parses the workflow as text and asserts schedule `0 0 * * 1-5`, `workflow_dispatch`, four exact targets, three secret names, `concurrency`, CPU PyTorch installation, Hugging Face cache, and no literal credential values.

- [ ] **Step 2: Run the workflow test and verify RED**

Run: `../../../.venv/bin/pytest tests/test_news_sync_workflow.py -v`

Expected: FAIL because the workflow file does not exist.

- [ ] **Step 3: Implement the workflow**

Use Python 3.12, pip cache, `actions/cache` for `~/.cache/huggingface`, CPU PyTorch before requirements, `permissions: contents: read`, `timeout-minutes`, and one concurrency group with `cancel-in-progress: false`.

- [ ] **Step 4: Document repository-secret setup without values**

Add GitHub Settings → Secrets and variables → Actions instructions for `NEWSAPI_AI_KEY`, `SUPABASE_URL`, and `SUPABASE_SECRET_KEY`. State that the workflow must be manually dispatched once before relying on cron.

- [ ] **Step 5: Run workflow test and Python CI-equivalent checks**

Run: `../../../.venv/bin/pytest tests/test_news_sync_workflow.py -v`

Run: `../../../.venv/bin/pytest -q`

Run from repository root: `.venv/bin/ruff check backend/analysis/text/`

Expected: all commands PASS.

- [ ] **Step 6: Commit Task 5**

```bash
git add .github/workflows/news-supabase-sync.yml backend/analysis/text/README.md backend/analysis/text/tests/test_news_sync_workflow.py
git commit -m "ci(text): schedule weekday news sync"
```

### Task 6: Frontend Supabase Insight Reader and Per-Section Fallback

**Files:**
- Create: `frontend/lib/providers/supabase-insights.ts`
- Create: `frontend/lib/providers/supabase-insights.test.ts`
- Modify: `frontend/lib/providers/index.ts`
- Modify: `frontend/lib/providers/providers.test.ts`

**Interfaces:**
- Produces: `loadSupabaseSentiment(code: string, client: SupabaseClient) -> Promise<SupabaseSentimentResult>`.
- Produces: `loadSupabaseFinancial(code: string, client: SupabaseClient) -> Promise<FinancialSnapshot | null>`.
- Produces: `SupabaseSentimentResult = { historical: SentimentData | null; live: LiveSentimentSummary | null; headlines: Headline[] }`, where `headlines` is newest-first and limited to three.
- Produces: `LiveSentimentSummary = { score: number; scoreStd: number | null; articleCount: number; publisherCount: number; status: NewsTrackStatus; asOf: string; windowStart: string; windowEnd: string; coverage: NewsTrackCoverage }`.
- Consumes: existing `getSupabaseClient`, `SentimentData`, `FinancialSnapshot`, and fixture providers.

- [ ] **Step 1: Write failing row-mapping tests with a fake query client**

Assert historical rows are ordered ascending after fetching the latest 20 non-null days, live track fields remain separate from historical graph points, articles are newest-first and limited to three, and latest financial snapshot maps all six metrics and basis strings.

- [ ] **Step 2: Add mixed-source and fallback Review Focus tests**

Cover: no client, query exception, empty all sections, live-only rows, historical-only rows, and financial-only rows. Assert each section independently uses Supabase when complete and its fixture otherwise.

- [ ] **Step 3: Run frontend provider tests and verify RED**

Run from `frontend`: `pnpm test:unit`

Expected: FAIL because `supabase-insights` and live summary types do not exist.

- [ ] **Step 4: Implement focused row mappers and provider composition**

Keep Supabase query code out of `index.ts`; that file only chooses Supabase results per section and falls back to existing providers. Never use a backend secret in frontend code.

- [ ] **Step 5: Run provider tests**

Run from `frontend`: `pnpm test:unit`

Expected: PASS.

- [ ] **Step 6: Commit Task 6**

```bash
git add frontend/lib/providers/supabase-insights.ts frontend/lib/providers/supabase-insights.test.ts frontend/lib/providers/index.ts frontend/lib/providers/providers.test.ts
git commit -m "feat(frontend): read insights from Supabase"
```

### Task 7: Stock Insight UI, Provenance, and Final Verification

**Files:**
- Modify: `frontend/app/components/insight-cards.tsx`
- Modify: `frontend/lib/providers/index.ts`
- Modify: `frontend/lib/types.ts` if the live summary crosses the shared component boundary
- Modify: `frontend/lib/copy-glossary.ts` only if a new user-facing term needs the approved easy-language mapping
- Modify: `frontend/lib/providers/providers.test.ts`
- Modify: relevant existing component tests under `frontend/`

**Interfaces:**
- Consumes: Task 6 live summary, historical days, three headlines, financial snapshot, and per-section provenance.
- Produces: the existing stock detail screen with separate recent-24-hour summary and historical graph behavior.

- [ ] **Step 1: Write failing UI/provider assertions**

Assert the recent mood line uses live sentiment when present, the chart continues to use historical data, exactly three representative articles appear, `partial` adds a neutral coverage notice, and fallback provenance is visibly distinct from real data provenance.

- [ ] **Step 2: Run focused frontend tests and verify RED**

Run from `frontend`: `pnpm test:unit`

Expected: FAIL on missing live-summary rendering.

- [ ] **Step 3: Implement the UI behavior without investment advice**

Use descriptive copy such as “최근 24시간 뉴스 분위기” and “수집 범위 일부”; include the `as_of` 기준시각 and source. Do not add buy/sell language or treat sentiment as a recommendation.

- [ ] **Step 4: Run all frontend checks**

Run from `frontend`: `pnpm lint`

Run from `frontend`: `pnpm test:unit`

Run from `frontend`: `pnpm build`

Run from `frontend`: `pnpm test:e2e`

Expected: all commands PASS.

- [ ] **Step 5: Run full repository-relevant verification**

Run from repository root: `.venv/bin/ruff check backend/analysis/text/`

Run from `backend/analysis/text`: `../../../.venv/bin/pytest -q`

Run: `git diff --check origin/main...HEAD`

Expected: Python lint/tests, frontend lint/build/E2E, and diff check all PASS.

- [ ] **Step 6: Review the final diff for secrets and scope**

Run: `git diff --name-only origin/main...HEAD`

Run: `git grep -nE "SUPABASE_SECRET_KEY=.+|NEWSAPI_AI_KEY=.+" -- ':!docs/superpowers/**' ':!.env.example'`

Expected: only intended backend/workflow/frontend/docs files; no credential values.

- [ ] **Step 7: Commit Task 7**

```bash
git add frontend/app/components/insight-cards.tsx frontend/lib/providers/index.ts frontend/lib/types.ts frontend/lib/copy-glossary.ts frontend/lib/providers/providers.test.ts
git commit -m "feat(frontend): show live Supabase news evidence"
```

### Task 8: Manual Handoff Without Secret Transmission

**Files:**
- No code changes unless verification reveals a documentation gap.

**Interfaces:**
- Consumes: merged workflow and documented secret names.
- Produces: a user handoff checklist; the agent never requests actual key values in chat.

- [ ] **Step 1: Report the three required secret names and Dashboard path**

Tell the repository administrator to enter values at GitHub → Settings → Secrets and variables → Actions. Do not ask them to paste keys into chat.

- [ ] **Step 2: Provide the first-run sequence**

Instruct: add secrets, manually run “News Supabase Sync,” verify four successful ticker lines, verify the five Supabase tables, run historical/DART backfill, then open each of the four stock pages.

- [ ] **Step 3: Stop before external secret entry and scheduled-run verification**

The code task is complete when automated tests pass. Actual key registration and first live API execution remain explicit user actions because the agent does not possess or transmit the credentials.
