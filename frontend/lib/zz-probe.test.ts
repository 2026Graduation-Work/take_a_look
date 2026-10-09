import assert from "node:assert/strict";
import test from "node:test";

test("필수 체크 차단 확인용 — 일부러 실패", () => assert.equal(1, 2));
