import { strict as assert } from "node:assert";
import { test } from "vitest";
import { checkFile, matchesSource, suggestedAnchor } from "./workspace.ts";
import type { ChatResult, Source } from "./contracts.ts";

const source: Source = {
  source_kind: "csv_demo", metric_ids: ["MOBILE_ACTIVATIONS"], dimensions: ["REGION"],
  row_count: 31, coverage_start: "2026-07-01", coverage_end: "2026-07-31",
  source_fingerprint: "a".repeat(64), uploaded_at: "2026-08-01T00:00:00Z",
};

test("date anchor comes from source coverage, including year and leap-day boundaries", () => {
  assert.equal(suggestedAnchor(source), "2026-08-01");
  assert.equal(suggestedAnchor({ ...source, coverage_end: "2026-12-31" }), "2027-01-01");
  assert.equal(suggestedAnchor({ ...source, coverage_end: "2028-02-28" }), "2028-02-29");
});

test("receipts are displayed only for the currently selected source", () => {
  const result = { receipt: { source_fingerprint: source.source_fingerprint } } as ChatResult;
  assert.equal(matchesSource(result, source), true);
  assert.equal(matchesSource(result, { ...source, source_fingerprint: "b".repeat(64) }), false);
  assert.equal(matchesSource(null, source), false);
  assert.equal(matchesSource(result, null), false);
  assert.equal(matchesSource({ receipt: null } as ChatResult, source), false);
});

test("file checks give actionable errors before upload", () => {
  assert.equal(checkFile({ name: "demo.csv", size: 20 }, 100), null);
  assert.equal(checkFile({ name: "DEMO.CSV", size: 100 }, 100), null);
  assert.match(checkFile({ name: "data.xlsx", size: 20 }, 100)!, /csv/);
  assert.match(checkFile({ name: "demo.csv", size: 0 }, 100)!, /empty/);
  assert.match(checkFile({ name: "demo.csv", size: 101 }, 100)!, /limit/);
});
