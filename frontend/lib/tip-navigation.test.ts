import assert from "node:assert/strict";
import { test } from "node:test";
import { readingHref, readingReturnPath, tipHref, tipPage, tipPageCount, tipReturnPath, tipTopic, topicForCategory } from "./tip-navigation.ts";

test("팁 주제는 알려진 분류만 선택하며 전체와 직접 진입의 기본값을 구분한다", () => {
  assert.equal(tipTopic("all", "habits"), "all");
  assert.equal(tipTopic(["habits", "costs"]), "habits");
  assert.equal(tipTopic(undefined, "habits"), "habits");
  assert.equal(tipTopic("not-a-topic"), "all");
  assert.equal(tipTopic("__proto__"), "all");
  assert.equal(topicForCategory("계산 착각"), "calculation");
  assert.equal(topicForCategory("제도와 비용"), "costs");
});

test("돌아가기는 허용된 서비스 화면과 선택 탭만 보존하고 외부 주소는 거부한다", () => {
  assert.equal(tipReturnPath("/stocks/005930?tab=company#details"), "/stocks/005930?tab=company#details");
  assert.equal(tipReturnPath("/"), "/");
  assert.equal(tipReturnPath(["/portfolio", "/performance"]), "/portfolio");
  assert.equal(tipReturnPath("/performance"), "/performance");
  assert.equal(tipReturnPath("/portfolio"), "/portfolio");
  for (const invalid of [undefined, "https://example.com", "//example.com", "/\\example.com", "/\n/example.com", "/tips/loss-recovery", "/login", "/api/private"]) {
    assert.equal(tipReturnPath(invalid), undefined, String(invalid));
  }
});

test("목록에서 상세로 갈 때 전체 주제와 원래 화면을 주소에 담는다", () => {
  const url = new URL(tipHref({ id: "loss-recovery", topic: "all", returnTo: "/stocks/005930?tab=company" }), "http://localhost");
  assert.equal(url.pathname, "/tips/loss-recovery");
  assert.equal(url.searchParams.get("category"), "all");
  assert.equal(url.searchParams.get("returnTo"), "/stocks/005930?tab=company");
  assert.equal(tipHref({ topic: "habits" }), "/tips?category=habits");
  assert.equal(tipHref(), "/tips");
});


test("페이지 번호는 첫 중복 값을 사용하고 유효한 범위 안으로 제한한다", () => {
  assert.equal(tipPageCount(42), 7);
  assert.equal(tipPageCount(0), 1);
  assert.equal(tipPage(undefined, 42), 1);
  assert.equal(tipPage("2", 42), 2);
  assert.equal(tipPage(["2", "5"], 42), 2);
  assert.equal(tipPage("999", 42), 7);
  for (const invalid of ["-1", "0", "1.5", "text", "Infinity"]) assert.equal(tipPage(invalid, 42), 1);
  assert.equal(tipPage("2", 1), 1);
  const pageLink = new URL(tipHref({ topic: "habits", page: 2, returnTo: "/performance" }), "http://localhost");
  assert.equal(pageLink.searchParams.get("page"), "2");
  assert.equal(pageLink.searchParams.get("category"), "habits");
  assert.equal(pageLink.searchParams.get("returnTo"), "/performance");
});


test("안내 화면을 오가도 진입 화면의 주소와 선택 상태를 유지한다", () => {
  const origin = "/stocks/005930?tab=company#details";
  assert.equal(readingReturnPath("/stocks/005930", "?tab=company", "#details"), origin);
  for (const path of ["/guide", "/glossary", "/tips", "/tips/loss-recovery"]) {
    const href = readingHref(path, origin);
    const url = new URL(href, "https://local.invalid");
    assert.equal(readingReturnPath(path, url.search), origin);
  }
  assert.equal(readingHref("/guide"), "/guide");
  assert.equal(readingReturnPath("/guide", "?returnTo=https://example.com"), undefined);
  assert.equal(readingReturnPath("/tips", "?returnTo=%2Ftips"), undefined);
  assert.equal(readingReturnPath("/login", ""), undefined);
});
