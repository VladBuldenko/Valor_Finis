// Pure paging logic of an offset-paged list (VF-MVP-BETA-001: Expenses and
// Income). Nothing here touches React, the network or money: it only decides
// which request to make next, which received rows to show and which footer the
// list shows. It generalises the execution-history paging
// (features/financial-rules/execution-history-data.ts) to any list whose rows
// have a string `id` and whose server answer is { items, total, limit, offset }.
//
// Offset paging over a newest-first list is NOT a snapshot. A record added
// while the user pages pushes later rows down, so the same row can appear on
// two pages. The rules below never skip a row because of that (the next offset
// counts what was RECEIVED) and never show one twice (rows are de-duplicated by
// id, first occurrence wins), but they do not promise a gap-free or
// point-in-time view; refreshing reloads the pages already loaded.
//
// `total` is a record COUNT supplied by the server for the whole list. It is
// shown as "N of M" and is never summed, computed or presented as a money
// total: the loaded rows are only a part of the history.

// The page size the Expenses and Income lists request. The server accepts 1-100
// and defaults to 50; 25 keeps a first page quick on a slow connection.
export const LIST_PAGE_SIZE = 25;

// What GET /expenses?limit=&offset= and GET /income?limit=&offset= answer.
export type Page<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
};

// The query string of one page request, e.g. "/api/v1/income?limit=25&offset=50".
// A value the server would reject (422) is a programming error here, so it
// throws instead of being sent: the page size is 1-100 and the offset is a
// non-negative integer.
export const MAX_LIST_PAGE_SIZE = 100;

export function pagedPath(path: string, limit: number, offset: number): string {
  if (!Number.isInteger(limit) || limit < 1 || limit > MAX_LIST_PAGE_SIZE) {
    throw new RangeError(`Page size must be a whole number from 1 to ${MAX_LIST_PAGE_SIZE}.`);
  }

  if (!Number.isInteger(offset) || offset < 0) {
    throw new RangeError("Page offset must be a whole number of 0 or more.");
  }

  return `${path}?limit=${limit}&offset=${offset}`;
}

export const receivedCount = (pages: readonly { items: readonly unknown[] }[]): number =>
  pages.reduce((sum, page) => sum + page.items.length, 0);

// The offset of the next page, or undefined when nothing more should be asked
// for: every row the server counted was received, or the last page was empty
// (asking again would loop on the same empty answer).
export function nextPageOffset(last: Page<unknown>, received: number): number | undefined {
  if (last.items.length === 0) {
    return undefined;
  }

  return received < last.total ? received : undefined;
}

export type MergedList<T> = {
  // First occurrence wins, server order kept.
  items: T[];
  // Rows the server sent, duplicates included (this is what the offset counts).
  received: number;
  // The newest page's total number of records.
  total: number;
  duplicatesDropped: number;
  hasMore: boolean;
  // The last page was empty although the total says more exist.
  stalled: boolean;
};

export function mergePages<T extends { id: string }>(pages: readonly Page<T>[]): MergedList<T> {
  const seen = new Set<string>();
  const items: T[] = [];

  for (const page of pages) {
    for (const item of page.items) {
      if (!seen.has(item.id)) {
        seen.add(item.id);
        items.push(item);
      }
    }
  }

  const received = receivedCount(pages);
  const last = pages[pages.length - 1];

  if (last === undefined) {
    return { items, received, total: 0, duplicatesDropped: 0, hasMore: false, stalled: false };
  }

  return {
    items,
    received,
    total: last.total,
    duplicatesDropped: received - items.length,
    hasMore: nextPageOffset(last, received) !== undefined,
    stalled: last.items.length === 0 && received < last.total,
  };
}

// ------------------------------------------------------------ screen state

export type PagedFooter = "none" | "load_more" | "loading_more" | "next_page_error" | "end" | "stalled";

export type PagedStateInput = {
  // The query has produced pages at some point (kept across later failures).
  hasData: boolean;
  itemCount: number;
  isError: boolean;
  isFetchNextPageError: boolean;
  isFetchingNextPage: boolean;
  hasMore: boolean;
  stalled: boolean;
};

export type PagedState = {
  // "empty" only when the server answered and the list really is empty.
  phase: "loading" | "error" | "empty" | "list";
  footer: PagedFooter;
  // A refresh failed while earlier rows are still shown.
  refreshError: boolean;
};

// One place that decides which state the list is in, so an error is never shown
// as "nothing yet" and a failed later page never hides rows already loaded.
export function derivePagedState(input: PagedStateInput): PagedState {
  if (!input.hasData) {
    return { phase: input.isError ? "error" : "loading", footer: "none", refreshError: false };
  }

  const refreshError = input.isError && !input.isFetchNextPageError;

  if (input.itemCount === 0) {
    return { phase: "empty", footer: "none", refreshError };
  }

  let footer: PagedFooter;

  if (input.isFetchingNextPage) {
    footer = "loading_more";
  } else if (input.isFetchNextPageError) {
    footer = "next_page_error";
  } else if (input.stalled) {
    footer = "stalled";
  } else if (input.hasMore) {
    footer = "load_more";
  } else {
    footer = "end";
  }

  return { phase: "list", footer, refreshError };
}

export const PAGED_COPY = {
  loadMore: "Load more",
  loadingMore: (what: string): string => `Loading more ${what}`,
  loadMoreLabel: (shown: number, total: number, what: string): string =>
    `Load more ${what}, showing ${shown} of ${total}`,
  shown: (shown: number, total: number): string => `Showing ${shown} of ${total}`,
  nextPageFailed: (what: string): string => `Could not load more ${what}. The ones above are still shown.`,
  retryMore: (what: string): string => `Retry loading more ${what}`,
  end: (what: string): string => `That is all your ${what}.`,
  stalled: (what: string): string => `More ${what} exist but none could be loaded right now. Pull down to refresh.`,
  paging: "Newer records can appear while you scroll, which can move older ones down. Pull down to refresh the list.",
} as const;
