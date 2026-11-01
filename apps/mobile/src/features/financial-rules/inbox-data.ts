// Pure Inbox logic (VF-020F4): bounded paging, source states and the shared
// attention indicator. Dashboard and Inbox both go through these functions, on
// the same query data, so they cannot disagree. Nothing here counts items for
// display or computes money.
import type { EvaluationStatus } from "./financial-rule-evaluation-trigger.ts";
import type { PaginatedResponse, RuleAlert, RuleProposal } from "./financial-rule.types.ts";

export const INBOX_PAGE_SIZE = 20;
// One initial page plus at most two more, per source (design sheet D2).
export const INBOX_MAX_PAGES = 3;
export const RECENT_EXECUTIONS_LIMIT = 5;

// ---------------------------------------------------------------- paging

export type BoundedPages<T> = {
  items: T[];
  // The backend's total for the filter (metadata only; never shown as a count).
  total: number;
  // True only when the backend metadata proves every item was received.
  complete: boolean;
  pagesFetched: number;
  // Alerts only: false means the alerts schema is missing in this environment.
  available: boolean;
};

type Page<T> = PaginatedResponse<T> & { available?: boolean };

// Fetches a first page and at most `maxPages - 1` more, stopping as soon as
// the metadata says everything arrived. If the cap is reached with items
// remaining, the result is INCOMPLETE and the caller must not treat it as
// "nothing else exists".
export async function fetchBoundedPages<T extends { id: string }>(
  fetchPage: (offset: number) => Promise<Page<T>>,
  maxPages: number = INBOX_MAX_PAGES,
): Promise<BoundedPages<T>> {
  const seen = new Set<string>();
  const items: T[] = [];
  let offset = 0;
  let pagesFetched = 0;
  let total = 0;
  let available = true;
  let complete = false;

  while (pagesFetched < maxPages) {
    const page = await fetchPage(offset);

    pagesFetched += 1;
    total = page.total;

    if (page.available === false) {
      available = false;
      complete = false;
      break;
    }

    for (const item of page.items) {
      if (!seen.has(item.id)) {
        seen.add(item.id);
        items.push(item);
      }
    }

    offset += page.items.length;

    if (offset >= page.total) {
      complete = true;
      break;
    }

    // An empty page while the total says more remain cannot be advanced.
    if (page.items.length === 0) {
      break;
    }
  }

  return { items, total, complete, pagesFetched, available };
}

// ------------------------------------------------------- indicator input

export type SourceStatus = "loading" | "error" | "success";

export type SourceState<T> = {
  status: SourceStatus;
  items: readonly T[];
  complete: boolean;
  available: boolean;
};

export type QueryLike<T> = {
  isError: boolean;
  isSuccess: boolean;
  data: BoundedPages<T> | undefined;
};

export function sourceStateFromQuery<T>(query: QueryLike<T>): SourceState<T> {
  const status: SourceStatus = query.isError ? "error" : query.isSuccess ? "success" : "loading";

  // Items of a failed or loading source are not trusted (stale data after a
  // failed refetch must not decide anything).
  if (status !== "success" || !query.data) {
    return { status, items: [], complete: false, available: true };
  }

  return {
    status,
    items: query.data.items,
    complete: query.data.complete,
    available: query.data.available,
  };
}

// ------------------------------------------------------------- indicator

export type InboxIndicator = "attention" | "clear" | "unknown";

export function isProposalActionable(proposal: Pick<RuleProposal, "status" | "expires_at">, now: number): boolean {
  if (proposal.status !== "awaiting_confirmation") {
    return false;
  }

  const expires = Date.parse(proposal.expires_at);

  // An unreadable expiry is not trusted as "still open".
  return Number.isFinite(expires) && expires > now;
}

export const isAlertActionable = (alert: Pick<RuleAlert, "acknowledged_at">): boolean =>
  alert.acknowledged_at === null;

export type IndicatorInput = {
  proposals: SourceState<Pick<RuleProposal, "status" | "expires_at">>;
  alerts: SourceState<Pick<RuleAlert, "acknowledged_at">>;
  // Evaluation joins the necessary sources only once it was attempted.
  evaluation: EvaluationStatus;
  now: number;
};

// attention: a loaded actionable proposal or unacknowledged alert exists; a
//   failed, loading or incomplete other source cannot cancel it.
// clear: proposals and alerts are authoritatively complete and available, hold
//   nothing actionable, and (if attempted) evaluation fully succeeded.
// unknown: everything else. Execution history never takes part.
export function deriveInboxIndicator(input: IndicatorInput): InboxIndicator {
  const hasProposal = input.proposals.status === "success" && input.proposals.items.some((item) => isProposalActionable(item, input.now));
  const hasAlert = input.alerts.status === "success" && input.alerts.available && input.alerts.items.some(isAlertActionable);

  if (hasProposal || hasAlert) {
    return "attention";
  }

  const proposalsSettled = input.proposals.status === "success" && input.proposals.complete;
  const alertsSettled = input.alerts.status === "success" && input.alerts.complete && input.alerts.available;
  const evaluationSettled = input.evaluation === "not_attempted" || input.evaluation === "succeeded";

  return proposalsSettled && alertsSettled && evaluationSettled ? "clear" : "unknown";
}

export type IndicatorPresentation = { marker: string; accessibilityLabel: string };

// Text, not colour; no number; never the word "unread".
export function inboxIndicatorPresentation(indicator: InboxIndicator): IndicatorPresentation {
  switch (indicator) {
    case "attention":
      return { marker: "Needs attention", accessibilityLabel: "Inbox, needs attention" };
    case "clear":
      return { marker: "Up to date", accessibilityLabel: "Inbox, up to date" };
    case "unknown":
      return { marker: "Status unknown", accessibilityLabel: "Inbox, status unknown" };
    default: {
      const exhaustive: never = indicator;

      throw new Error(`Unhandled indicator: ${String(exhaustive)}`);
    }
  }
}
