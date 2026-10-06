import assert from "node:assert/strict";
import test from "node:test";
import { formatKstDateTime } from "./display.ts";

test("formatKstDateTime shows UTC timestamps in Korean time and leaves dates alone", () => {
  assert.equal(formatKstDateTime("2026-10-06T03:53:12.940604+00:00"), "2026.10.06 12:53");
  assert.equal(formatKstDateTime("2026-10-02"), "2026.10.02");
});
