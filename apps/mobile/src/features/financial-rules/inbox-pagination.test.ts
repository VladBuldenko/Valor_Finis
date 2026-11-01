import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { INBOX_MAX_PAGES, INBOX_PAGE_SIZE, fetchBoundedPages } from "./inbox-data.ts";
import { nextAlertOffset } from "./inbox-alerts.ts";
import { listAlertsRequest, listProposalsRequest } from "./financial-rule-requests.ts";
import type { RuleAlertList } from "./financial-rule.types.ts";

const page = (ids: string[], total: number, offset: number, extra: object = {}) => ({
  items: ids.map((id) => ({ id })), total, limit: INBOX_PAGE_SIZE, offset, ...extra,
});

describe("bounded paging", () => {
  it("one page is enough when the metadata says so (one request)", async () => {
    let calls = 0;
    const result = await fetchBoundedPages(async (offset) => { calls += 1; return page(["a", "b"], 2, offset); });

    assert.deepEqual([calls, result.complete, result.items.length], [1, true, 2]);
  });

  it("an empty first page with total 0 is complete", async () => {
    const result = await fetchBoundedPages(async (offset) => page([], 0, offset));

    assert.equal(result.complete, true);
  });

  it("follows offsets from the received items and stops when complete (3 pages)", async () => {
    const offsets: number[] = [];
    const result = await fetchBoundedPages(async (offset) => {
      offsets.push(offset);

      return page(Array.from({ length: offset === 40 ? 5 : 20 }, (_, i) => `i${offset + i}`), 45, offset);
    });

    assert.deepEqual(offsets, [0, 20, 40]);
    assert.equal(result.complete, true);
    assert.equal(result.items.length, 45);
  });

  it("never exceeds one initial page plus two more, however large the total", async () => {
    let calls = 0;
    const result = await fetchBoundedPages(async (offset) => {
      calls += 1;

      return page(Array.from({ length: 20 }, (_, i) => `i${offset + i}`), 100_000, offset);
    });

    assert.equal(calls, INBOX_MAX_PAGES);
    assert.equal(INBOX_MAX_PAGES, 3);
    assert.equal(result.complete, false);
    assert.equal(result.items.length, 60);
  });

  it("a first page that merely looks empty does not prove completeness", async () => {
    const result = await fetchBoundedPages(async (offset) => page([], 7, offset));

    assert.equal(result.complete, false);
    assert.equal(result.pagesFetched, 1);
  });

  it("de-duplicates items that shifted between pages", async () => {
    const result = await fetchBoundedPages(async (offset) =>
      offset === 0 ? page(["a", "b"], 3, 0) : page(["b", "c"], 3, 2));

    assert.deepEqual(result.items.map((item) => item.id), ["a", "b", "c"]);
  });

  it("alerts available:false stops at once and is neither complete nor empty-successful", async () => {
    let calls = 0;
    const result = await fetchBoundedPages(async (offset) => { calls += 1; return page([], 0, offset, { available: false }); });

    assert.deepEqual([calls, result.available, result.complete], [1, false, false]);
  });

  it("a failing page rejects (the source goes to error, not partial-success)", async () => {
    await assert.rejects(fetchBoundedPages(async () => { throw new Error("boom"); }));
  });
});

describe("request construction", () => {
  it("proposals are filtered to awaiting_confirmation, alerts to acknowledged=false", () => {
    assert.equal(
      listProposalsRequest({ status: "awaiting_confirmation", limit: 20, offset: 20 }).path,
      "/api/v1/rule-proposals?limit=20&offset=20&status=awaiting_confirmation",
    );
    assert.equal(listAlertsRequest({ acknowledged: false, limit: 20, offset: 0 }).path, "/api/v1/rule-alerts?limit=20&offset=0&acknowledged=false");
  });
});

describe("alerts screen manual paging", () => {
  const list = (items: number, total: number, available = true): RuleAlertList => ({
    items: Array.from({ length: items }, (_, i) => ({ id: String(i) })) as RuleAlertList["items"], total, limit: 20, offset: 0, available,
  });

  it("offers the next offset only while the backend total says more exist", () => {
    assert.equal(nextAlertOffset(list(20, 45), 20), 20);
    assert.equal(nextAlertOffset(list(5, 45), 45), undefined);
    assert.equal(nextAlertOffset(list(20, 20), 20), undefined);
    assert.equal(nextAlertOffset(list(0, 5), 0), undefined);
    assert.equal(nextAlertOffset(list(0, 0, false), 0), undefined);
  });
});
