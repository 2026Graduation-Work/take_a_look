# Mobile QA M01–M06 Implementation Plan

> Execute inline with systematic-debugging and test-driven-development. The user authorized push and PR creation on 2026-10-26 after local review. Merge and deployment remain outside this task.

**Goal:** Resolve the six observed mobile QA items without reorganizing the existing screens or touching screenshot import/OCR.

**Spec:** The 2026-10-26 mobile QA report in the original checkout, `docs/qa/2026-10-26-mobile/README.md`.

**Architecture:** Use the public stock master in demo holdings search; share the existing device-local signal horizon between dashboard and detail; keep chart labels at readable size through chart-local scrolling. Gate public portfolio values by the matching request and keep tooltip content in the visible chart viewport. Correct the privacy notice to match the existing logout behavior.

**Tech stack:** Existing Next.js/React/TypeScript, Supabase public reads, Recharts, Playwright. Frozen schemas and scoring are unchanged. Existing issue #425/#426/#427 and OCR remain outside scope.

## Tasks

- [x] Establish clean baseline on `5543f64` and add failing mobile regression tests.
- [x] M01: share public catalog loading between header and holdings; handle loading, missing matches and read failures without silently ignoring Enter. Verify demo onboarding and portfolio, exact code/name, unknown query, duplicates and delayed reads.
- [x] M02: extract device-local horizon state, consume it in chart detail, and derive direction/band/features/source from the same chosen snapshot. Preserve direct/default 4-week behavior and show the existing segmented choice in the detail heading.
- [x] M03: prevent SVG text scaling below the design's 13px minimum; constrain horizontal scrolling to the chart. Check 320/390/430px and page overflow.
- [x] M04: associate closes/signals, daily changes and strong lists with their request keys; show loading until matching results arrive and never restore fixture signals after an empty live read. Separate layout minimum sizes from displayed money/weights.
- [x] M05: correct demo deletion notice to the actual `signOut` cleanup; reuse existing logout behavior tests. No prose-mirroring tests.
- [x] M06: portal click tooltip into a visible, non-scrolling chart host with bounded width; verify old/latest points, scroll extremes, period changes and Escape.
- [x] Run targeted E2E, full unit suite, frontend lint/build and relevant existing E2E; inspect local mobile UI with Computer Use.
- [x] Record results and local review URL; leave the branch available for user review.

## Review focus

Delayed responses must not repaint a different horizon or query. Empty/failed public reads must not imply fixture signals or fake one-won holdings. Invalid device storage must fall back safely. Visible chart labels must not force page overflow. Tooltips must stay readable even when the underlying timeline is many screens wide.
