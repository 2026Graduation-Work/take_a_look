# 구형 `chart_signal_detail_v1` 계약 기록

**현재 일일 실행·공개에는 사용하지 않는다.** 현재 계약과 프론트 조회 필드는 [README.md](../README.md), 기계 검증 규격은 [chart_signal_detail_v2.schema.json](chart_signal_detail_v2.schema.json)을 참조한다. 아래 내용은 구형 v1 연구 경로를 위한 기록이다.

Schema: `chart_signal_detail_v1.schema.json`; validator:
`serving.contracts.validate_snapshot`. The four examples in
`examples/` cover normal, both directions, no cases and unavailable.
This contract is separate from frozen `schema/chart_output.schema.json`.

Each JSON identifies a stock code and exact-date stock name, actual data date, H5/H20, profile, release and
batch. H5 maps to `aggressive`, H20 to `stable`. A release binds the fold-6
model, model feature order, 2019–2025 fold OOS case ledger, fixed similarity
policy, and SHA-256 hashes. The same batch ID covers both horizons for every
expected stock. A published batch is visible only after every snapshot exists.

`inference.scores.down/neutral/up` are the LightGBM class 0/1/2 outputs.
Class 2 means the upper barrier was reached **before** the lower barrier
within H traded sessions; same-day both goes to class 0. These are model
outputs, not guaranteed future probabilities. `inference.close` is adjusted
close and `sigma` is the observed 20-traded-session log-return standard
deviation. `barriers.up/down` use H5 multipliers 1.75/1.50 or H20 3.75/3.00.
The model's stored input barrier features are different: 1.5/1.2. Feature
contributions are signed class-2 **raw margin** components, not percentage
points, returns or causal effects. The top five use absolute contribution,
with feature-name tie order; the displayed value is the actual input.

A similar case must be the same stock, horizon and training policy, be a
completed 2019–2025 fold OOS prediction, and satisfy all three unrounded
comparisons:

```text
abs(old_up - current_up) <= 0.01
abs(old_down - current_down) <= 0.01
abs(old_Sigma - current_Sigma) <= current_Sigma * 0.10
```

These are initial operating widths, not statistically optimal widths. If
current Sigma is zero, only exactly zero historical Sigma is eligible. There
is no minimum sample count, widening, forced nearest N or substitute stock.
Fold model outputs are compared across years and adjacent H-session outcomes
overlap; the screen must disclose both limits.

For each completed historical case, the next H traded sessions are observed
within the legacy `int(H*2.5)` source-row search cap. A halt is skipped. A high
at or above the upper price sets `up_hit`; a close at or below the lower price
sets `down_hit`. Observation continues after either event. Missing/incomplete
outcomes are excluded with an audit reason; they do not become `neither`.
`both_count` is included in both `up_count` and `down_count`, and
`neither_count = sample_count - up_count - down_count + both_count`. Both rates
have `sample_count` as denominator and are derived from integer counts.
They are independent historical touch frequencies, not model hit rate or
future rise/fall probabilities.

`cases.status` is `available` for one or more matches, `no_cases` for a
successful zero-row query, `unavailable` if the source or inference cannot be
used. A zero denominator yields null rates and the screen shows `—`.
`period_start/end`, `observed_through`, fold counts and artifact hashes allow
the statement to be audited. `prices.history` contains at most 60 observed
adjusted daily closes and volumes with dates; there is no projected path,
return band, histogram, H10 or whole-market comparison in this contract.

The snapshot stock code is independent of the legacy `stocks` demo catalog, so
new KOSPI names come from the exact-date universe in `stock_name`.

The migration stores release metadata in `chart_releases`, one H5/H20 pair and
status in `chart_batches`, and each full snapshot JSON in
`chart_signal_snapshots`. The raw historical ledger stays as Parquet in the
service data root. `latest_chart_signal_snapshots` exposes only the newest
published batch. Staging, failed and withdrawn batches are invisible to
ordinary readers; only the service role may write or publish.
