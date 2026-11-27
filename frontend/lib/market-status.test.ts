import assert from "node:assert/strict";
import test from "node:test";
import { showLocalAsOf, staleLabel } from "./market-status.ts";

const at = (kst: string) => Date.parse(`${kst}+09:00`);

test("게시 전(18:47 KST 전): 전 거래일이 최신이고 하루 늦은 게시도 정상", () => {
  assert.equal(staleLabel("2026-10-20", at("2026-10-21T12:00:00")), null);
  assert.equal(staleLabel("2026-10-19", at("2026-10-21T01:00:00")), null);
  assert.equal(staleLabel("2026-10-19", at("2026-10-21T18:46:00")), null);
  assert.equal(staleLabel("2026-10-16", at("2026-10-21T12:00:00")), "5일 전 데이터예요");
});

test("게시 후(18:47 KST부터): 오늘이 게시됐어야 할 날", () => {
  assert.equal(staleLabel("2026-10-20", at("2026-10-21T19:00:00")), null);
  assert.equal(staleLabel("2026-10-19", at("2026-10-21T18:47:00")), "2일 전 데이터예요");
});

test("주말: 금 종가가 월 18:47 전까지 최신", () => {
  for (const kst of ["2026-10-24T10:00:00", "2026-10-25T23:00:00", "2026-10-26T18:46:00"]) {
    assert.equal(staleLabel("2026-10-23", at(kst)), null);
  }
  assert.equal(staleLabel("2026-10-22", at("2026-10-26T19:00:00")), "4일 전 데이터예요");
  assert.equal(staleLabel("2026-10-22", at("2026-10-24T10:00:00")), null);
});

test("공휴일: KRX 휴장 평일은 밀린 날로 세지 않는다", () => {
  // 10/9(금) 한글날, 10/8(목) 종가가 10/12(월) 저녁에도 하루 늦은 정도
  assert.equal(staleLabel("2026-10-08", at("2026-10-12T20:00:00")), null);
  assert.equal(staleLabel("2026-10-08", at("2026-10-13T20:00:00")), "5일 전 데이터예요");
  // 12/31(목), 1/1(금) 연말연시 휴장
  assert.equal(staleLabel("2026-12-30", at("2027-01-04T20:00:00")), null);
});

test("아주 오래된 데이터", () => {
  assert.equal(staleLabel("2025-12-30", at("2026-10-06T12:00:00")), "280일 전 데이터예요");
});

test("시장 바와 같은 최신 기준일만 생략하고 다른 시점과 갱신 지연은 남긴다", () => {
  const now = at("2026-10-21T12:00:00");
  assert.equal(showLocalAsOf("2026-10-20", "2026-10-20", now), false);
  assert.equal(showLocalAsOf("2026-10-19", "2026-10-20", now), true);
  assert.equal(showLocalAsOf("2026-10-16", "2026-10-16", now), true);
  assert.equal(showLocalAsOf("2026-10-20", "", now), true);
  assert.equal(showLocalAsOf(undefined, "2026-10-20", now), false);
  assert.equal(showLocalAsOf("", "2026-10-20", now), false);
});
