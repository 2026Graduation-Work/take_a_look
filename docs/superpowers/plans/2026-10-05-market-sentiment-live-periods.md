# Market Sentiment Live and Period Views Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show six stocks' deterministic historical sentiment across daily, monthly, and yearly views while presenting today's NewsAPI.ai result as a distinct live observation.

**Architecture:** Preserve BigKinds historical and NewsAPI.ai live records as separate tracks. Add a pure frontend aggregation helper that converts daily historical rows into article-count weighted periods; the Market panel consumes that helper and overlays a current live marker. Extend the existing Supabase writer and GitHub workflow with an operator-triggered live-row reset and six-stock historical backfill flow.

**Tech Stack:** Next.js 16, React 19, TypeScript/node:test, Recharts, Python 3.12/pytest, Supabase PostgREST, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-05-market-sentiment-live-periods-design.md`

## Global Constraints

- Do not change files under `schema/`; the JSON contracts are frozen.
- Keep `historical` (BigKinds) and `live` (NewsAPI.ai) separate, with source and collection time visible in the UI.
- Aggregate month/year values by relevant-article count weighted mean; zero/article-free dates have no weight.
- Do not delete or recreate Supabase tables, policies, indexes, or schema migrations.
- Follow `frontend/DESIGN.md`: the live marker uses existing chart color and a restrained circular marker, not a new semantic color.
- Never add trading instructions or predictive price curves.

## Review Focus

- A daily score with zero articles must not affect a monthly or yearly score; Task 1 test pins this.
- A stale live observation must not receive a current/live marker; Task 2 test pins this.
- A partial historical import must upsert provided dates without erasing unrelated historical dates; Task 3 test pins this.
- Reset must only remove the six target codes' `live` rows and leave every `historical` row intact; Task 4 test pins this.
- NAVER and EcoPro BM must have no invented model/financial values when validated source data is absent; Task 5 test pins this.

---

### Task 1: Deterministic sentiment period aggregation

**Files:**
- Modify: `frontend/lib/providers/index.ts`
- Test: `frontend/lib/providers/providers.test.ts`

**Interfaces:**
- Produces: `aggregateSentimentPeriods(days: SentimentDay[], period: "day" | "month" | "year"): SentimentDay[]`.
- Consumes: existing `SentimentDay` fields `date`, `score`, and `articleCount`.

- [ ] **Step 1: Write failing aggregation tests**

Test daily passthrough, a month where scores are weighted by article counts, a year spanning two months, and zero-article days being ignored.

- [ ] **Step 2: Run the targeted test to verify it fails**

Run: `cd frontend && pnpm exec tsx --test lib/providers/providers.test.ts`

Expected: FAIL because `aggregateSentimentPeriods` does not exist.

- [ ] **Step 3: Implement `aggregateSentimentPeriods`**

Group ISO dates by day/month/year. For each non-daily group, calculate `sum(score * articleCount) / sum(articleCount)` and retain the summed article count; omit groups with no positive weight.

- [ ] **Step 4: Run the targeted test to verify it passes**

Run: `cd frontend && pnpm exec tsx --test lib/providers/providers.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/providers/index.ts frontend/lib/providers/providers.test.ts
git commit -m "feat(frontend): aggregate sentiment by period"
```

### Task 2: Historical retrieval and market-panel period UI

**Files:**
- Modify: `frontend/lib/providers/supabase-insights.ts`
- Modify: `frontend/lib/providers/supabase-insights.test.ts`
- Modify: `frontend/app/components/insight-cards.tsx`
- Test: `frontend/lib/providers/providers.test.ts`
- Test: `frontend/tests/e2e/onboarding.spec.ts` or a focused new market-tab spec

**Interfaces:**
- Consumes: `aggregateSentimentPeriods`, `LiveSentimentSummary`, and `marketSentimentView`.
- Produces: accessible nested period tabs and a historical data series with an optional current live marker.

- [ ] **Step 1: Write failing data and UI tests**

Assert that the Supabase historical query does not cap results at 20, that `일별/월별/연별` has one selected tab, and that a current live result renders the `오늘 Live` marker while a stale one does not.

- [ ] **Step 2: Run targeted tests to verify they fail**

Run: `cd frontend && pnpm exec tsx --test lib/providers/supabase-insights.test.ts lib/providers/providers.test.ts`

Expected: FAIL because the query still limits to 20 and period controls/marker are absent.

- [ ] **Step 3: Implement retrieval and MarketPanel controls**

Remove only the historical query's 20-row limit. Add local selected-period state using the existing segmented-tab accessibility pattern. Render the selected aggregate series; append a visually restrained marker only when `marketSentimentView` reports a current live record. Keep live source/timestamp/article count beside the chart and retain source chips.

- [ ] **Step 4: Remove non-news source text from the representative article block**

Keep title and publisher in the article disclosure. Do not render price-source text there; retain section-level news provenance.

- [ ] **Step 5: Run targeted tests and build verification**

Run: `cd frontend && pnpm exec tsx --test lib/providers/supabase-insights.test.ts lib/providers/providers.test.ts && pnpm build`

Expected: PASS and successful build.

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/providers/supabase-insights.ts frontend/lib/providers/supabase-insights.test.ts frontend/lib/providers/providers.test.ts frontend/app/components/insight-cards.tsx frontend/tests/e2e
git commit -m "feat(frontend): add sentiment period views"
```

### Task 3: Six-stock historical import and catalog support

**Files:**
- Modify: `backend/analysis/text/value_pipeline/supabase_sync.py`
- Modify: `backend/analysis/text/tests/test_news_tracks.py`
- Modify: `.github/workflows/news-supabase-sync.yml`
- Modify: `backend/analysis/text/README.md`
- Modify: `frontend/lib/mock-data.ts`
- Modify: `supabase/seed.sql`
- Test: `backend/analysis/text/tests/test_news_sync_workflow.py`
- Test: frontend catalog/provider tests

**Interfaces:**
- Produces: six-stock target map and a CLI command that builds BigKinds historical tracks directly from root `data/<code>/` workbooks, then persists them.
- Consumes: the existing deterministic `run_historical_cycle` and `persist_news_track`.

- [ ] **Step 1: Write failing six-stock tests**

Assert that NAVER and EcoPro BM are in the target map, workflow target list, seed catalog, and UI-known-stock mapping. Assert a historical import invokes the existing deterministic historical builder for a supplied target/range.

- [ ] **Step 2: Run the relevant tests to verify they fail**

Run: `cd backend/analysis/text && ../../../.venv/bin/pytest tests/test_news_sync_workflow.py tests/test_news_tracks.py -q`

Expected: FAIL because the target map and workflow have four stocks only.

- [ ] **Step 3: Implement six-stock target and historical backfill support**

Add `035420:네이버` and `247540:에코프로비엠` to the shared target definitions and workflow. Add an explicit historical import command accepting targets/date range and using root `data/` without changing the database schema. Register two catalog entries with unavailable states for evidence that has no validated source.

- [ ] **Step 4: Run backend/frontend targeted tests**

Run: `cd backend/analysis/text && ../../../.venv/bin/pytest tests/test_news_sync_workflow.py tests/test_news_tracks.py -q && cd ../../../frontend && pnpm exec tsx --test lib/providers/providers.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/text .github/workflows/news-supabase-sync.yml frontend/lib/mock-data.ts supabase/seed.sql
git commit -m "feat(text): add six-stock sentiment sync"
```

### Task 4: Safe operator-only live reset

**Files:**
- Modify: `backend/analysis/text/value_pipeline/supabase_store.py`
- Modify: `backend/analysis/text/value_pipeline/supabase_sync.py`
- Modify: `backend/analysis/text/tests/test_supabase_store.py`
- Modify: `backend/analysis/text/tests/test_news_sync_workflow.py`
- Modify: `.github/workflows/news-supabase-sync.yml`
- Modify: `backend/analysis/text/README.md`

**Interfaces:**
- Produces: `clear_live_news(client, stock_codes: Collection[str]) -> None` and a manual `reset-live` workflow mode.
- Consumes: trusted `SupabaseRestClient` service-role credentials and the six-code target map.

- [ ] **Step 1: Write failing reset-scope tests**

Assert exactly three delete requests, each constrained to `track=eq.live` and the six target codes; assert no request targets `historical`.

- [ ] **Step 2: Run targeted tests to verify they fail**

Run: `cd backend/analysis/text && ../../../.venv/bin/pytest tests/test_supabase_store.py tests/test_news_sync_workflow.py -q`

Expected: FAIL because no reset API or workflow mode exists.

- [ ] **Step 3: Implement scoped deletion and manual workflow mode**

Add PostgREST delete support if absent. Delete only `live` rows from tracks, daily values, and articles for the six codes. Add a manual workflow selection that clears rows, then runs the normal six-stock live sync in the same job.

- [ ] **Step 4: Run targeted tests to verify they pass**

Run: `cd backend/analysis/text && ../../../.venv/bin/pytest tests/test_supabase_store.py tests/test_news_sync_workflow.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/text .github/workflows/news-supabase-sync.yml
git commit -m "feat(text): add scoped live reset workflow"
```

### Task 5: Full verification and delivery evidence

**Files:**
- Modify only if verification exposes a defect.

**Interfaces:**
- Consumes: all prior task interfaces.
- Produces: evidence that frontend, backend, and workflow behavior match the spec.

- [ ] **Step 1: Run the complete relevant backend suite**

Run: `cd backend/analysis/text && ../../../.venv/bin/pytest -q`

Expected: PASS.

- [ ] **Step 2: Run frontend verification**

Run: `cd frontend && pnpm exec tsx --test lib/providers/providers.test.ts lib/providers/supabase-insights.test.ts && pnpm build`

Expected: PASS.

- [ ] **Step 3: Inspect the diff against the spec and commit any test-driven repairs**

Verify source provenance, weighted aggregation, six-stock targets, reset scope, and no schema-file changes.

