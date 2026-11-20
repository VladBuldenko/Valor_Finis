// VF-MVP-BETA-001: the pure paging rules of the Expenses and Income lists.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  LIST_PAGE_SIZE,
  MAX_LIST_PAGE_SIZE,
  PAGED_COPY,
  derivePagedState,
  mergePages,
  nextPageOffset,
  pagedPath,
  receivedCount,
  type Page,
  type PagedStateInput,
} from "./paged-list.ts";

type Row = { id: string };

const rows = (from: number, to: number): Row[] =>
  Array.from({ length: to - from }, (_, index) => ({ id: `r${from + index}` }));

const page = (items: Row[], total: number, offset: number, limit = LIST_PAGE_SIZE): Page<Row> => ({
  items,
  total,
  limit,
  offset,
});

describe("the page request", () => {
  it("is limit and offset on the list path", () => {
    assert.equal(pagedPath("/api/v1/income", 25, 50), "/api/v1/income?limit=25&offset=50");
    assert.equal(pagedPath("/api/v1/expenses", 1, 0), "/api/v1/expenses?limit=1&offset=0");
  });

  it("the page size the screens use is one the server accepts", () => {
    assert.ok(LIST_PAGE_SIZE >= 1 && LIST_PAGE_SIZE <= MAX_LIST_PAGE_SIZE);
    assert.equal(MAX_LIST_PAGE_SIZE, 100);
  });

  it("never builds a request the server would reject", () => {
    for (const [limit, offset] of [[0, 0], [101, 0], [-1, 0], [1.5, 0], [Number.NaN, 0], [25, -1], [25, 0.5], [25, Number.NaN]]) {
      assert.throws(() => pagedPath("/api/v1/income", limit, offset), RangeError, `${limit}/${offset}`);
    }

    assert.doesNotThrow(() => pagedPath("/api/v1/income", 100, 0));
  });
});

describe("which page is asked for next", () => {
  it("continues from the number of rows RECEIVED while the server counts more", () => {
    assert.equal(nextPageOffset(page(rows(0, 25), 60, 0), 25), 25);
    assert.equal(nextPageOffset(page(rows(25, 50), 60, 25), 50), 50);
  });

  it("stops on the final page, whether it is full or short", () => {
    assert.equal(nextPageOffset(page(rows(50, 60), 60, 50), 60), undefined);
    assert.equal(nextPageOffset(page(rows(0, 25), 25, 0), 25), undefined);
  });

  it("stops on an empty page even though the total says more (no endless asking)", () => {
    assert.equal(nextPageOffset(page([], 60, 25), 25), undefined);
  });

  it("an empty list has no next page", () => {
    assert.equal(nextPageOffset(page([], 0, 0), 0), undefined);
  });

  it("counts received rows across pages", () => {
    assert.equal(receivedCount([page(rows(0, 25), 60, 0), page(rows(25, 40), 60, 25)]), 40);
    assert.equal(receivedCount([]), 0);
  });
});

describe("merging pages", () => {
  it("keeps server order and reports the newest total", () => {
    const merged = mergePages([page(rows(0, 25), 60, 0), page(rows(25, 50), 61, 25)]);

    assert.deepEqual(merged.items.map((row) => row.id), rows(0, 50).map((row) => row.id));
    assert.equal(merged.total, 61);
    assert.equal(merged.received, 50);
    assert.equal(merged.hasMore, true);
    assert.equal(merged.stalled, false);
  });

  it("shows a row repeated by a shifted page once, and still counts it as received", () => {
    // A record added meanwhile pushed r24 onto the second page.
    const merged = mergePages([page(rows(0, 25), 60, 0), page([{ id: "r24" }, ...rows(25, 49)], 61, 25)]);

    assert.equal(merged.items.length, 49);
    assert.equal(new Set(merged.items.map((row) => row.id)).size, 49);
    assert.equal(merged.received, 50, "the next offset counts what was received, so no row is skipped");
    assert.equal(merged.duplicatesDropped, 1);
  });

  it("is not 'more' once everything the server counted was received", () => {
    const merged = mergePages([page(rows(0, 25), 40, 0), page(rows(25, 40), 40, 25)]);

    assert.equal(merged.hasMore, false);
  });

  it("a short answer while more are counted is reported as stalled", () => {
    const merged = mergePages([page(rows(0, 25), 60, 0), page([], 60, 25)]);

    assert.equal(merged.stalled, true);
    assert.equal(merged.hasMore, false);
  });

  it("no pages is an empty, finished list", () => {
    assert.deepEqual(mergePages([]), {
      items: [], received: 0, total: 0, duplicatesDropped: 0, hasMore: false, stalled: false,
    });
  });
});

const base: PagedStateInput = {
  hasData: true,
  itemCount: 25,
  isError: false,
  isFetchNextPageError: false,
  isFetchingNextPage: false,
  hasMore: true,
  stalled: false,
};

describe("what the list shows", () => {
  it("loading before any answer, an error with nothing to show is never 'empty'", () => {
    assert.deepEqual(derivePagedState({ ...base, hasData: false, itemCount: 0 }), {
      phase: "loading", footer: "none", refreshError: false,
    });
    assert.deepEqual(derivePagedState({ ...base, hasData: false, itemCount: 0, isError: true }), {
      phase: "error", footer: "none", refreshError: false,
    });
  });

  it("an answered empty list is 'empty', without a footer", () => {
    assert.deepEqual(derivePagedState({ ...base, itemCount: 0, hasMore: false }), {
      phase: "empty", footer: "none", refreshError: false,
    });
  });

  it("Load more while more exist; the end when everything is loaded", () => {
    assert.equal(derivePagedState(base).footer, "load_more");
    assert.equal(derivePagedState({ ...base, hasMore: false }).footer, "end");
  });

  it("loading more keeps the rows and shows progress", () => {
    const state = derivePagedState({ ...base, isFetchingNextPage: true });

    assert.equal(state.phase, "list");
    assert.equal(state.footer, "loading_more");
  });

  it("a failed later page keeps the rows and offers Retry, and is not a refresh error", () => {
    const state = derivePagedState({ ...base, isError: true, isFetchNextPageError: true });

    assert.deepEqual(state, { phase: "list", footer: "next_page_error", refreshError: false });
  });

  it("a failed refresh with rows on screen keeps them and reports the refresh failure", () => {
    const state = derivePagedState({ ...base, isError: true });

    assert.equal(state.phase, "list");
    assert.equal(state.refreshError, true);
    assert.equal(state.footer, "load_more");
  });

  it("a stalled list says so instead of offering Load more again", () => {
    assert.equal(derivePagedState({ ...base, hasMore: false, stalled: true }).footer, "stalled");
  });
});

describe("the wording", () => {
  it("uses only the server's count for 'N of M' and never a money amount", () => {
    assert.equal(PAGED_COPY.shown(25, 120), "Showing 25 of 120");
    assert.equal(PAGED_COPY.loadMoreLabel(25, 120, "expenses"), "Load more expenses, showing 25 of 120");
    assert.match(PAGED_COPY.paging, /Pull down to refresh/);
  });
});
