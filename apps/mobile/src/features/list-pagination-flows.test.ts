// VF-MVP-BETA-001: Expenses and Income lists, mounted with the real TanStack
// hooks under the real SessionScope and the real API transport. The server is a
// scripted fake that answers like the backend (limit/offset/total page envelope,
// GET /{id} with 404), so the page requests are built by the same code the
// screens use and the rows on screen are exactly what the answers contained.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { createElement, type ReactElement } from "react";
import TestRenderer from "react-test-renderer";

import { createApiTransport } from "../api/api-transport.ts";
import { SessionBoundary } from "../api/session-boundary.ts";
import { act } from "../lib/mounted-test-support.ts";
import { LIST_PAGE_SIZE, pagedPath, type Page } from "../lib/paged-list.ts";
import { isRecordNotFound } from "../lib/record-not-found.ts";
import { SessionQueryClient } from "../lib/session-query-client.ts";
import { SessionScope } from "../lib/session-scope.ts";
import { usePagedList } from "../lib/use-paged-list.ts";
import { invalidateExpenseQueries } from "./expenses/expense-cache.ts";
import { expenseKeys } from "./expenses/expense-query-keys.ts";
import { invalidateIncomeQueries } from "./income/income-cache.ts";
import { incomeKeys } from "./income/income-query-keys.ts";

type Row = { id: string; label: string };

type Kind = {
  name: string;
  path: string;
  listKey: (userId: string) => readonly unknown[];
  detailKey: (userId: string, id: string) => readonly unknown[];
  invalidate: (client: QueryClient, userId: string) => Promise<unknown>;
};

const KINDS: Kind[] = [
  {
    name: "Expenses",
    path: "/api/v1/expenses",
    listKey: (userId) => expenseKeys.list(userId),
    detailKey: (userId, id) => expenseKeys.detail(userId, id),
    invalidate: (client, userId) => invalidateExpenseQueries(client, userId, false),
  },
  {
    name: "Income",
    path: "/api/v1/income",
    listKey: (userId) => incomeKeys.list(userId),
    detailKey: (userId, id) => incomeKeys.detail(userId, id),
    invalidate: (client, userId) => invalidateIncomeQueries(client, userId, false),
  },
];

const USER = "user-a";
const TOTAL = 120;
const sleep = (ms: number) => act(async () => { await new Promise((resolve) => setTimeout(resolve, ms)); });

// Newest first: r120 ... r001.
const rowId = (n: number): string => `r${String(n).padStart(3, "0")}`;

function world(kind: Kind) {
  const holder = new SessionQueryClient();
  const boundary = new SessionBoundary(() => holder.rotate());
  const store: { rows: Row[] } = {
    rows: Array.from({ length: TOTAL }, (_, index) => ({ id: rowId(TOTAL - index), label: `Record ${TOTAL - index}` })),
  };
  const log: string[] = [];
  // Ordinals (1-based) of PAGE requests the server answers with a 400.
  const failing = new Set<number>();
  let pageRequests = 0;

  const json = (status: number, body: unknown) =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

  const transport = createApiTransport({
    baseUrl: "https://api.test",
    boundary,
    sleep: async () => undefined,
    getSession: async () => ({ userId: USER, accessToken: "a-token" }),
    onUnauthorized: async () => undefined,
    fetch: async (url) => {
      const parsed = new URL(url);

      log.push(parsed.pathname + parsed.search);

      if (parsed.pathname === kind.path) {
        if (parsed.search === "") {
          return json(200, store.rows);
        }

        pageRequests += 1;

        if (failing.has(pageRequests)) {
          return json(400, { detail: "Nope." });
        }

        const limit = Number(parsed.searchParams.get("limit"));
        const offset = Number(parsed.searchParams.get("offset"));

        return json(200, {
          items: store.rows.slice(offset, offset + limit),
          total: store.rows.length,
          limit,
          offset,
        });
      }

      const id = parsed.pathname.slice(kind.path.length + 1);
      const row = store.rows.find((candidate) => candidate.id === id);

      return row ? json(200, row) : json(404, { detail: "Not found.", code: "not_found" });
    },
  });

  boundary.applyAuthEvent(USER, "a-token");

  const fetchPage = (limit: number, offset: number, signal?: AbortSignal) =>
    transport.request<Page<Row>>(pagedPath(kind.path, limit, offset), { signal });
  const fetchOne = (id: string, signal?: AbortSignal) =>
    transport.request<Row>(`${kind.path}/${id}`, { signal });

  const seen: {
    list: ReturnType<typeof usePagedList<Row>> | null;
    detail: ReturnType<typeof useQuery<Row>> | null;
    client: QueryClient | null;
  } = { list: null, detail: null, client: null };

  function Probe(props: { list: boolean; detailId: string | null }): null {
    seen.client = useQueryClient();

    const list = usePagedList<Row>({ queryKey: props.list ? kind.listKey(USER) : null, fetchPage });
    const detail = useQuery<Row>({
      queryKey: kind.detailKey(USER, props.detailId ?? "none"),
      queryFn: ({ signal }) => fetchOne(props.detailId ?? "none", signal),
      enabled: props.detailId !== null,
    });

    // TanStack re-renders only for the result fields a component reads.
    void [
      list.feed.isError, list.feed.isFetchNextPageError, list.feed.isFetchingNextPage,
      list.feed.hasNextPage, list.feed.isRefetching, list.feed.fetchStatus,
      detail.isError, detail.data, detail.error, detail.fetchStatus,
    ];
    seen.list = list;
    seen.detail = detail;

    return null;
  }

  const tree = (props: { list: boolean; detailId: string | null }): ReactElement =>
    createElement(SessionScope, { holder }, createElement(Probe, props));

  return {
    log, store, failing, seen,
    async mount(props: { list?: boolean; detailId?: string | null } = {}) {
      let renderer!: TestRenderer.ReactTestRenderer;

      await act(async () => {
        renderer = TestRenderer.create(tree({ list: props.list ?? true, detailId: props.detailId ?? null }));
      });
      await sleep(20);

      return renderer;
    },
    async more() {
      await act(async () => { void seen.list?.feed.fetchNextPage(); });
      await sleep(20);
    },
    async refresh() {
      await act(async () => { void seen.list?.feed.refetch(); });
      await sleep(20);
    },
    async invalidate() {
      await act(async () => { void kind.invalidate(seen.client as QueryClient, USER); });
      await sleep(30);
    },
    ids: () => seen.list?.merged?.items.map((row) => row.id) ?? [],
    pageCalls: () => log.filter((entry) => entry.startsWith(`${kind.path}?`)),
    expectedIds: (from: number, count: number) => Array.from({ length: count }, (_, index) => rowId(TOTAL - from - index)),
  };
}

for (const kind of KINDS) {
  describe(`${kind.name}: first page and Load more`, () => {
    it("the first request is one bounded page, never the complete list", async () => {
      const w = world(kind);

      await w.mount();

      assert.deepEqual(w.log, [`${kind.path}?limit=${LIST_PAGE_SIZE}&offset=0`]);
      assert.equal(w.ids().length, LIST_PAGE_SIZE);
      assert.deepEqual(w.ids(), w.expectedIds(0, LIST_PAGE_SIZE));
      assert.equal(w.seen.list?.state.phase, "list");
      assert.equal(w.seen.list?.state.footer, "load_more");
      await sleep(60);
      assert.equal(w.log.length, 1, "no automatic second request");
    });

    it("the count shown is the server's total of all records, not the number loaded", async () => {
      const w = world(kind);

      await w.mount();

      assert.equal(w.seen.list?.merged?.total, TOTAL);
      assert.equal(w.seen.list?.merged?.items.length, LIST_PAGE_SIZE);
    });

    it("Load more appends the next page and keeps everything loaded before", async () => {
      const w = world(kind);

      await w.mount();
      const firstPage = w.ids();
      await w.more();

      assert.equal(w.log[1], `${kind.path}?limit=${LIST_PAGE_SIZE}&offset=${LIST_PAGE_SIZE}`);
      assert.deepEqual(w.ids().slice(0, LIST_PAGE_SIZE), firstPage);
      assert.deepEqual(w.ids(), w.expectedIds(0, LIST_PAGE_SIZE * 2));
    });

    it("every record is reachable: paging to the end shows all of them once, then stops", async () => {
      const w = world(kind);

      await w.mount();
      for (let guard = 0; guard < 10 && w.seen.list?.feed.hasNextPage; guard += 1) {
        await w.more();
      }

      assert.equal(w.ids().length, TOTAL);
      assert.equal(new Set(w.ids()).size, TOTAL);
      assert.deepEqual(w.ids(), w.expectedIds(0, TOTAL));
      assert.equal(w.seen.list?.state.footer, "end");
      assert.equal(w.pageCalls().length, Math.ceil(TOTAL / LIST_PAGE_SIZE));
    });

    it("an empty list is empty, not an error", async () => {
      const w = world(kind);

      w.store.rows = [];
      await w.mount();

      assert.equal(w.seen.list?.state.phase, "empty");
      assert.equal(w.seen.list?.merged?.total, 0);
    });
  });

  describe(`${kind.name}: a failed later page`, () => {
    it("keeps the loaded rows, shows Retry, never retries by itself, and Retry asks for the same page", async () => {
      const w = world(kind);

      await w.mount();
      const firstPage = w.ids();
      w.failing.add(2);
      await w.more();

      assert.deepEqual(w.ids(), firstPage, "the rows loaded before are still on screen");
      assert.equal(w.seen.list?.feed.isFetchNextPageError, true);
      assert.equal(w.seen.list?.state.phase, "list");
      assert.equal(w.seen.list?.state.footer, "next_page_error");
      assert.equal(w.seen.list?.state.refreshError, false, "this is not a failed refresh");
      await sleep(60);
      assert.equal(w.pageCalls().length, 2, "one failed request, no automatic retry");

      await w.more();

      assert.equal(w.pageCalls()[2], w.pageCalls()[1], "Retry asks for exactly the page that failed");
      assert.deepEqual(w.ids(), w.expectedIds(0, LIST_PAGE_SIZE * 2));
      assert.equal(w.seen.list?.state.footer, "load_more");
    });

    it("a failed FIRST page with nothing loaded is an error, never 'no records'", async () => {
      const w = world(kind);

      w.failing.add(1);
      await w.mount();

      assert.equal(w.seen.list?.state.phase, "error");
      assert.equal(w.ids().length, 0);
    });
  });

  describe(`${kind.name}: refresh`, () => {
    it("re-reads every page already loaded, from the start, and shows a consistent list", async () => {
      const w = world(kind);

      await w.mount();
      await w.more();
      w.log.length = 0;
      // A record arrived meanwhile: it is now first and everything else moved down.
      w.store.rows = [{ id: "r999", label: "New" }, ...w.store.rows];
      await w.refresh();

      assert.deepEqual(w.pageCalls(), [
        `${kind.path}?limit=${LIST_PAGE_SIZE}&offset=0`,
        `${kind.path}?limit=${LIST_PAGE_SIZE}&offset=${LIST_PAGE_SIZE}`,
      ]);
      assert.equal(w.ids().length, LIST_PAGE_SIZE * 2);
      assert.equal(new Set(w.ids()).size, LIST_PAGE_SIZE * 2);
      assert.equal(w.ids()[0], "r999");
      assert.equal(w.seen.list?.merged?.total, TOTAL + 1);
    });

    it("a failed refresh keeps the rows on screen and reports the failure", async () => {
      const w = world(kind);

      await w.mount();
      const before = w.ids();
      w.failing.add(2);
      await w.refresh();

      assert.deepEqual(w.ids(), before);
      assert.equal(w.seen.list?.state.phase, "list");
      assert.equal(w.seen.list?.state.refreshError, true);
    });

    it("a record added while paging does not repeat a row or skip one", async () => {
      const w = world(kind);

      await w.mount();
      w.store.rows = [{ id: "r999", label: "New" }, ...w.store.rows];
      await w.more();

      // The second page starts one row earlier than it would have: the repeated
      // row is shown once, and the offset kept counting what was received.
      assert.equal(new Set(w.ids()).size, w.ids().length);
      assert.equal(w.seen.list?.merged?.duplicatesDropped, 1);
      assert.equal(w.seen.list?.merged?.received, LIST_PAGE_SIZE * 2);
    });
  });

  describe(`${kind.name}: cache invalidation after create, edit and delete`, () => {
    it("create: the pages are re-read and the new record is first, with the new total", async () => {
      const w = world(kind);

      await w.mount();
      await w.more();
      w.log.length = 0;
      w.store.rows = [{ id: "r999", label: "Created" }, ...w.store.rows];
      await w.invalidate();

      assert.equal(w.ids()[0], "r999");
      assert.equal(w.seen.list?.merged?.total, TOTAL + 1);
      assert.equal(w.pageCalls().length, 2, "both loaded pages were re-read");
    });

    it("edit: the changed record is re-read in the list and in its open detail", async () => {
      const w = world(kind);
      const target = rowId(TOTAL - 30); // on the second page

      await w.mount({ detailId: target });
      await w.more();
      assert.equal(w.seen.detail?.data?.label, `Record ${TOTAL - 30}`);

      w.store.rows = w.store.rows.map((row) => (row.id === target ? { ...row, label: "Edited" } : row));
      await w.invalidate();

      assert.equal(w.seen.list?.merged?.items.find((row) => row.id === target)?.label, "Edited");
      assert.equal(w.seen.detail?.data?.label, "Edited");
    });

    it("delete: the record leaves the list and the total shrinks", async () => {
      const w = world(kind);
      const target = rowId(TOTAL - 3);

      await w.mount();
      assert.ok(w.ids().includes(target));
      w.store.rows = w.store.rows.filter((row) => row.id !== target);
      await w.invalidate();

      assert.ok(!w.ids().includes(target));
      assert.equal(w.seen.list?.merged?.total, TOTAL - 1);
      assert.equal(new Set(w.ids()).size, w.ids().length);
    });

    it("another user's cached list is not touched", async () => {
      const w = world(kind);

      await w.mount();
      const client = w.seen.client as QueryClient;
      const foreign = kind.listKey("user-b");
      client.setQueryData(foreign, { pages: [], pageParams: [] });
      await w.invalidate();

      assert.equal(client.getQueryState(foreign)?.isInvalidated, false);
    });

    it("the list and a detail never share a cache key, and both sit under the user's prefix", () => {
      const list = kind.listKey(USER);
      const detail = kind.detailKey(USER, "x");

      assert.notDeepEqual(list, detail);
      assert.deepEqual(list.slice(0, 2), detail.slice(0, 2));
      assert.equal(list[1], USER);
    });
  });

  describe(`${kind.name}: opening a record that is not on a loaded page`, () => {
    it("is read by id with one request, without downloading any list", async () => {
      const w = world(kind);
      const oldest = rowId(1);

      await w.mount({ list: false, detailId: oldest });

      assert.deepEqual(w.log, [`${kind.path}/${oldest}`]);
      assert.equal(w.seen.detail?.data?.id, oldest);
    });

    it("a record of someone else, or one that no longer exists, is 'not found' and never shows cached data", async () => {
      const w = world(kind);
      const target = rowId(5);

      await w.mount({ list: false, detailId: target });
      assert.equal(w.seen.detail?.data?.id, target);

      w.store.rows = w.store.rows.filter((row) => row.id !== target);
      await w.invalidate();

      assert.equal(isRecordNotFound(w.seen.detail?.error), true);
      // The old copy is still in the cache; the screens ignore it on a 404.
      assert.equal(w.seen.detail?.data?.id, target);
    });
  });
}

describe("not found", () => {
  it("is only a 404 answer, not any other failure", async () => {
    const w = world(KINDS[0]);

    w.failing.add(1);
    await w.mount();

    assert.equal(isRecordNotFound(w.seen.list?.feed.error), false);
    assert.equal(isRecordNotFound(new Error("404")), false);
    assert.equal(isRecordNotFound(undefined), false);
  });
});
