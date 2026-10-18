import assert from "node:assert/strict";
import { test } from "node:test";
import { featureGroup, featureLabel } from "./featureLabels.ts";
import { FORBIDDEN_COPY } from "./copy-rules.ts";

// 2026-10-13 운영 latest_chart_signal_snapshots에 실제로 나온 피처명 전체(#257) + 수급 모델 피처
const SHOWN = [
  "std_20",
  "wvma_20",
  "imin_60",
  "vstd_20",
  "rsqr_20",
  "std_10",
  "wvma_60",
  "vwap_0",
  "klow",
  "cord_30",
  "wvma_5",
  "kup",
  "imin_30",
  "min_60",
  "klen",
  "std_60",
  "rsqr_30",
  "std_30",
  "min_20",
  "rsqr_10",
  "corr_20",
  "Barrier_Up",
  "imxd_60",
  "rsv_60",
  "imin_20",
  "cntn_60",
  "cord_20",
  "qtld_20",
  "max_5",
  "corr_10",
  "rank_30",
  "min_30",
  "cord_10",
  "vstd_5",
  "qtld_30",
  "imin_5",
  "cord_60",
  "min_5",
  "sumd_20",
  "rsqr_60",
  "sump_20",
  "corr_5",
  "high_0",
  "corr_30",
  "low_0",
  "corr_60",
  "roc_20",
  "resi_60",
  "Barrier_Down",
  "resi_30",
  "sumn_20",
  "vma_20",
  "imax_60",
  "sump_30",
  "resi_5",
  "max_20",
  "std_5",
  "roc_60",
  "rsqr_5",
  "cntd_60",
  "max_30",
  "cntd_30",
  "sumn_30",
  "beta_60",
  "cntd_20",
  "min_10",
  "flow_individual_1",
  "flow_individual_5",
  "flow_individual_20",
  "flow_institution_1",
  "flow_institution_5",
  "flow_institution_20",
  "flow_foreign_1",
  "flow_foreign_5",
  "flow_foreign_20",
];

test("화면에 나오는 피처명이 모두 쉬운 말로 바뀐다", () => {
  for (const name of SHOWN) {
    const label = featureLabel(name, "모델 입력 상승 쪽 가격");
    assert.ok(!/[A-Za-z_]/.test(label), `${name} → ${label}`);
    assert.ok(label.length <= 16, `${name} → ${label} (${label.length}자)`);
    assert.ok(!FORBIDDEN_COPY.some(({ pattern }) => pattern.test(label)), label);
  }
});

test("사전에 없는 피처는 원문 대신 묶음 이름", () => {
  assert.equal(featureLabel("news_sentiment_7"), "뉴스 분위기");
  assert.equal(featureLabel("dart_roe"), "재무");
  assert.equal(featureLabel("flow_pension_5"), "거래·수급");
  assert.equal(featureLabel("unknown_x", "raw_name"), "가격 흐름");
  assert.equal(featureLabel("unknown_x", "최근 쏠림"), "최근 쏠림");
  assert.equal(featureGroup("vsumd_99"), "거래·수급");
});
