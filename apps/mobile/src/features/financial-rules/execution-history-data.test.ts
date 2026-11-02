// VF-020F6: paging, key and state logic of the execution history (pure).
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  HISTORY_PAGE_SIZE,
  deriveHistoryState,
  historyKeyFilters,
  historyRequestFilters,
  isFiltered,
  mergeHistoryPages,
  nextHistoryOffset,
  parseRuleParam,
  type HistoryStateInput,
} from "./execution-history-data.ts";
import { financialRuleKeys } from "./financial-rule-query-keys.ts";
import { planRuleInvalidation } from "./financial-rule-invalidation.ts";
import { listExecutionsRequest, isUuid } from "./financial-rule-requests.ts";
import { EXECUTION_STATUSES } from "./financial-rule.types.ts";
import { RULE_1, RULE_2, ids, page } from "./history-fixtures.test-support.ts";

describe("requests and keys", () => {
  it("the page is 20 and absent filters are left out of the request", () => {
    assert.equal(HISTORY_PAGE_SIZE, 20);
    assert.deepEqual(historyRequestFilters({ ruleId: null, status: null }, 0), { limit: 20, offset: 0 });
    assert.equal(
      listExecutionsRequest(historyRequestFilters({ ruleId: RULE_1, status: "blocked" }, 40)).path,
      `/api/v1/rule-executions?limit=20&offset=40&rule_id=${RULE_1}&status=blocked`,
    );
  });

  it("only GET /rule-executions is ever requested", () => {
    const spec = listExecutionsRequest(historyRequestFilters({ ruleId: null, status: "executed" }, 0));

    assert.equal(spec.method, "GET");
    assert.equal(spec.body, undefined);
  });

  it("the key holds the user, both filters and the page size", () => {
    const base = historyKeyFilters({ ruleId: null, status: null });
    const key = financialRuleKeys.executionHistory("user-a", base);

    assert.deepEqual(key, ["rule-executions", "user-a", "history", { rule_id: null, status: null, limit: 20 }]);
  });

  it("each user, rule filter and status filter is its own entry", () => {
    const pairs: [string, string | null, (typeof EXECUTION_STATUSES)[number] | null][] = [];

    for (const user of ["a", "b"]) {
      for (const ruleId of [null, RULE_1, RULE_2]) {
        for (const status of [null, ...EXECUTION_STATUSES]) {
          pairs.push([user, ruleId, status]);
        }
      }
    }

    const keys = new Set(
      pairs.map(([user, ruleId, status]) =>
        JSON.stringify(financialRuleKeys.executionHistory(user, historyKeyFilters({ ruleId, status }))),
      ),
    );

    assert.equal(keys.size, pairs.length, "no two (user, rule, status) triples share an entry");
  });

  it("is distinct from the Inbox's and the plain list's entries, yet under the executions family", () => {
    const history = financialRuleKeys.executionHistory("a", { limit: 20 });

    assert.notDeepEqual(history, financialRuleKeys.inboxExecutions("a"));
    assert.notDeepEqual(history, financialRuleKeys.executionList("a", { limit: 20 }));
    assert.deepEqual(history.slice(0, 2), financialRuleKeys.executionsFamily("a"));
  });

  it("refuses to build a key without a user", () => {
    assert.throws(() => financialRuleKeys.executionHistory("", { limit: 20 }));
  });

  it("the existing invalidation events already reach the history entry", () => {
    const touched = (event: Parameters<typeof planRuleInvalidation>[1]) =>
      planRuleInvalidation("a", event).some((prefix) => JSON.stringify(prefix) === JSON.stringify(financialRuleKeys.executionsFamily("a")));

    assert.ok(touched({ type: "rule_status_changed", ruleId: RULE_1, action: "pause" }));
    assert.ok(touched({ type: "proposal_decided", decision: "confirm", status: "executed" }));
  });
});

describe("next offset", () => {
  it("is what was received, not page x limit", () => {
    assert.equal(nextHistoryOffset(page(ids(20), 45, 0), 20), 20);
    assert.equal(nextHistoryOffset(page(ids(20), 45, 20), 40), 40);
    assert.equal(nextHistoryOffset(page(ids(18), 45, 20), 38), 38);
  });

  it("stops when everything was received", () => {
    assert.equal(nextHistoryOffset(page(ids(5), 45, 40), 45), undefined);
    assert.equal(nextHistoryOffset(page(ids(20), 20, 0), 20), undefined);
    assert.equal(nextHistoryOffset(page(ids(20), 19, 0), 20), undefined, "received beyond a shrunken total");
  });

  it("an empty page ends paging even if the total says more (no loop)", () => {
    assert.equal(nextHistoryOffset(page([], 45, 40), 40), undefined);
  });
});

describe("merging pages", () => {
  it("keeps server order and drops a row that reappears on the next page", () => {
    const merged = mergeHistoryPages([page(ids(20), 45, 0), page(["e19", ...ids(19, 20)], 46, 20)]);

    assert.equal(merged.items.length, 39);
    assert.equal(new Set(merged.items.map((e) => e.id)).size, merged.items.length);
    assert.deepEqual(merged.items.slice(18, 22).map((e) => e.id), ["e18", "e19", "e20", "e21"]);
    assert.equal(merged.received, 40);
    assert.equal(merged.duplicatesDropped, 1);
    assert.equal(merged.total, 46, "the newest page's total wins");
    assert.equal(merged.hasMore, true);
  });

  it("the first occurrence wins when the same id differs between pages", () => {
    const merged = mergeHistoryPages([
      page(["x"], 2, 0, () => ({ status: "awaiting_confirmation" })),
      page(["x", "y"], 2, 1, () => ({ status: "executed" })),
    ]);

    assert.equal(merged.items.find((e) => e.id === "x")?.status, "awaiting_confirmation");
  });

  it("no more pages once every counted row was received", () => {
    const merged = mergeHistoryPages([page(ids(20), 25, 0), page(ids(5, 20), 25, 20)]);

    assert.deepEqual([merged.hasMore, merged.stalled, merged.items.length], [false, false, 25]);
  });

  it("an empty last page with rows missing is stalled, not endless and not complete", () => {
    const merged = mergeHistoryPages([page(ids(20), 45, 0), page([], 45, 20)]);

    assert.deepEqual([merged.hasMore, merged.stalled], [false, true]);
  });

  it("an empty first page with total 0 is simply empty", () => {
    const merged = mergeHistoryPages([page([], 0, 0)]);

    assert.deepEqual([merged.items.length, merged.hasMore, merged.stalled], [0, false, false]);
  });

  it("no pages at all is empty and not 'more'", () => {
    assert.deepEqual(mergeHistoryPages([]).hasMore, false);
  });
});

describe("rule_id route parameter", () => {
  it("none, valid, malformed and array forms", () => {
    assert.deepEqual(parseRuleParam(undefined), { ruleId: null, invalid: false });
    assert.deepEqual(parseRuleParam(""), { ruleId: null, invalid: false });
    assert.deepEqual(parseRuleParam(RULE_1), { ruleId: RULE_1, invalid: false });
    assert.deepEqual(parseRuleParam("not-a-uuid"), { ruleId: null, invalid: true });
    assert.deepEqual(parseRuleParam([RULE_1, RULE_1]), { ruleId: null, invalid: true });
    assert.equal(isUuid(RULE_1), true);
  });

  it("isFiltered", () => {
    assert.equal(isFiltered({ ruleId: null, status: null }), false);
    assert.equal(isFiltered({ ruleId: RULE_1, status: null }), true);
    assert.equal(isFiltered({ ruleId: null, status: "expired" }), true);
  });
});

describe("screen state", () => {
  const base: HistoryStateInput = {
    signedIn: true, hasData: true, itemCount: 3, isError: false, isFetchNextPageError: false,
    isFetchingNextPage: false, hasMore: false, stalled: false, filtered: false,
  };
  const state = (over: Partial<HistoryStateInput>) => deriveHistoryState({ ...base, ...over });

  it("signed out shows nothing private, whatever the cache says", () => {
    assert.deepEqual(state({ signedIn: false, hasData: true, itemCount: 5 }), { phase: "signed_out", footer: "none", refreshError: false });
  });

  it("loading, first-load error and empty are three different states", () => {
    assert.equal(state({ hasData: false }).phase, "loading");
    assert.equal(state({ hasData: false, isError: true }).phase, "error");
    assert.equal(state({ itemCount: 0 }).phase, "empty");
    assert.equal(state({ itemCount: 0, filtered: true }).phase, "empty_filtered");
  });

  it("an error with no data is never 'empty'", () => {
    for (const filtered of [true, false]) {
      assert.notEqual(state({ hasData: false, isError: true, itemCount: 0, filtered }).phase, "empty");
      assert.notEqual(state({ hasData: false, isError: true, itemCount: 0, filtered }).phase, "empty_filtered");
    }
  });

  it("footer: load more / loading / end / stalled", () => {
    assert.equal(state({ hasMore: true }).footer, "load_more");
    assert.equal(state({ hasMore: true, isFetchingNextPage: true }).footer, "loading_more");
    assert.equal(state({ hasMore: false }).footer, "end");
    assert.equal(state({ stalled: true }).footer, "stalled");
  });

  it("a later-page failure keeps the list and offers a retry for that page", () => {
    const failed = state({ hasMore: true, isError: true, isFetchNextPageError: true });

    assert.deepEqual(failed, { phase: "list", footer: "next_page_error", refreshError: false });
  });

  it("a failed refresh keeps the list and is reported separately", () => {
    const failed = state({ hasMore: true, isError: true });

    assert.deepEqual(failed, { phase: "list", footer: "load_more", refreshError: true });
    assert.equal(state({ itemCount: 0, isError: true }).refreshError, true);
  });

  it("the end is announced only when nothing more is counted", () => {
    assert.notEqual(state({ hasMore: true }).footer, "end");
  });
});
