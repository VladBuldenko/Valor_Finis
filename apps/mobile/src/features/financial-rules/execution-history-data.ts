// Pure paging and state logic of the execution history (VF-020F6). Nothing
// here touches React, the network or money: it only decides which request to
// make next and which of the received rows to show.
//
// Offset paging over a newest-first list is NOT a snapshot. A run recorded
// while the user pages pushes later rows down, so the same row can appear on
// two pages. The rules below never skip a row because of that (the next offset
// counts what was RECEIVED) and never show one twice (rows are de-duplicated by
// id), but they do not promise a gap-free or point-in-time view.
import { isUuid } from "./financial-rule-requests.ts";
import type {
  ExecutionStatus,
  RuleExecution,
  RuleExecutionFilters,
  RuleExecutionList,
} from "./financial-rule.types.ts";

export const HISTORY_PAGE_SIZE = 20;

export type HistoryFilters = { ruleId: string | null; status: ExecutionStatus | null };

export const NO_HISTORY_FILTERS: HistoryFilters = { ruleId: null, status: null };

export const isFiltered = (filters: HistoryFilters): boolean =>
  filters.ruleId !== null || filters.status !== null;

// The request for one page. Absent filters are left out entirely.
export function historyRequestFilters(filters: HistoryFilters, offset: number): RuleExecutionFilters {
  const request: RuleExecutionFilters = { limit: HISTORY_PAGE_SIZE, offset };

  if (filters.ruleId !== null) {
    request.rule_id = filters.ruleId;
  }

  if (filters.status !== null) {
    request.status = filters.status;
  }

  return request;
}

// The filter part of the query key, from the screen's filters.
export function historyKeyFilters(filters: HistoryFilters): {
  rule_id?: string;
  status?: ExecutionStatus;
  limit: number;
} {
  const key: { rule_id?: string; status?: ExecutionStatus; limit: number } = { limit: HISTORY_PAGE_SIZE };

  if (filters.ruleId !== null) {
    key.rule_id = filters.ruleId;
  }

  if (filters.status !== null) {
    key.status = filters.status;
  }

  return key;
}

export const receivedCount = (pages: readonly { items: readonly unknown[] }[]): number =>
  pages.reduce((sum, page) => sum + page.items.length, 0);

// The offset of the next page, or undefined when nothing more should be asked
// for: every row the server counted was received, or the last page was empty
// (asking again would loop on the same empty answer).
export function nextHistoryOffset(last: RuleExecutionList, received: number): number | undefined {
  if (last.items.length === 0) {
    return undefined;
  }

  return received < last.total ? received : undefined;
}

export type MergedHistory = {
  // First occurrence wins, server order kept.
  items: RuleExecution[];
  // Rows the server sent, duplicates included (this is what the offset counts).
  received: number;
  // The newest page's filtered total.
  total: number;
  duplicatesDropped: number;
  hasMore: boolean;
  // The last page was empty although the total says more exist.
  stalled: boolean;
};

export function mergeHistoryPages(pages: readonly RuleExecutionList[]): MergedHistory {
  const seen = new Set<string>();
  const items: RuleExecution[] = [];

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
    hasMore: nextHistoryOffset(last, received) !== undefined,
    stalled: last.items.length === 0 && received < last.total,
  };
}

// A `rule_id` route parameter comes from outside the app. An absent one means
// "all rules"; a malformed one is reported so the screen can say so instead of
// querying something else or throwing.
export function parseRuleParam(raw: string | string[] | undefined): { ruleId: string | null; invalid: boolean } {
  if (raw === undefined || raw === "") {
    return { ruleId: null, invalid: false };
  }

  if (typeof raw !== "string" || !isUuid(raw)) {
    return { ruleId: null, invalid: true };
  }

  return { ruleId: raw, invalid: false };
}

// ------------------------------------------------------------ screen state

export type HistoryPhase = "signed_out" | "loading" | "error" | "empty" | "empty_filtered" | "list";

export type HistoryFooter =
  | "none"
  | "load_more"
  | "loading_more"
  | "next_page_error"
  | "end"
  | "stalled";

export type HistoryStateInput = {
  signedIn: boolean;
  // The query has produced pages at some point (kept across later failures).
  hasData: boolean;
  itemCount: number;
  isError: boolean;
  isFetchNextPageError: boolean;
  isFetchingNextPage: boolean;
  hasMore: boolean;
  stalled: boolean;
  filtered: boolean;
};

export type HistoryState = {
  phase: HistoryPhase;
  footer: HistoryFooter;
  // A pull-to-refresh failed while earlier rows are still shown.
  refreshError: boolean;
};

// One place that decides which state the screen is in, so an error can never
// be shown as "no history" and a failed later page never hides loaded rows.
export function deriveHistoryState(input: HistoryStateInput): HistoryState {
  if (!input.signedIn) {
    return { phase: "signed_out", footer: "none", refreshError: false };
  }

  if (!input.hasData) {
    return {
      phase: input.isError ? "error" : "loading",
      footer: "none",
      refreshError: false,
    };
  }

  const refreshError = input.isError && !input.isFetchNextPageError;

  if (input.itemCount === 0) {
    return {
      phase: input.filtered ? "empty_filtered" : "empty",
      footer: "none",
      refreshError,
    };
  }

  let footer: HistoryFooter;

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
