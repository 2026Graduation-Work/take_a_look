import assert from "node:assert/strict";
import test from "node:test";
import { holdingValue } from "./portfolio-value.ts";

test("unknown or invalid prices never become a fabricated one-won holding", () => {
  assert.equal(holdingValue({ quantity: 12, avgBuyPrice: 0 }), null);
  assert.equal(holdingValue({ quantity: 12, avgBuyPrice: Number.NaN }), null);
  assert.equal(holdingValue({ quantity: 12, avgBuyPrice: 275000 }), 3300000);
});
