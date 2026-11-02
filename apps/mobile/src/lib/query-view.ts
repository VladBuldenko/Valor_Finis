// How a screen reads a TanStack query (VF-MOB-REFRESH-RETRY). Pure and
// Node-testable: no React, no React Native.
//
// The rules every screen follows through these helpers:
//  - Rows the screen already holds win. A failed REFRESH never replaces data
//    that was loaded earlier; it is reported next to the data instead.
//  - A failure with nothing loaded is an error with Retry, never an empty list.
//  - What the user may read about a failure comes from getUserFacingErrorMessage
//    (never the raw backend text, URL, path or token).
import { ApiError } from "../api/api-error.ts";
import { getUserFacingErrorMessage } from "../api/user-facing-error.ts";

export type QueryPhase = "loading" | "error" | "ready";

export type QueryShape = {
  data: unknown;
  isError: boolean;
};

// "ready" as soon as there is data, whatever happened since; "error" only when
// the query failed and has nothing to show; otherwise "loading".
export function queryPhase(query: QueryShape): QueryPhase {
  if (query.data !== undefined) {
    return "ready";
  }

  return query.isError ? "error" : "loading";
}

// A refresh failed while earlier data is still on screen.
export const refreshFailed = (query: QueryShape): boolean => query.isError && query.data !== undefined;

// The first phase to show for several queries that BOTH are needed to render a
// section. "error" wins over "loading" so a failed part cannot spin forever.
export function combinedPhase(queries: readonly QueryShape[]): QueryPhase {
  const phases = queries.map(queryPhase);

  if (phases.includes("error")) {
    return "error";
  }

  return phases.includes("loading") ? "loading" : "ready";
}

// What a single-query section shows. `refreshError` marks "content (or the
// empty message) with a failed-refresh notice above it".
export type BoundaryView =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "empty"; refreshError: boolean }
  | { kind: "content"; refreshError: boolean };

export function boundaryView<T>(query: QueryShape & { data: T | undefined }, isEmpty: (data: T) => boolean): BoundaryView {
  const phase = queryPhase(query);

  if (phase === "loading") {
    return { kind: "loading" };
  }

  if (phase === "error" || query.data === undefined) {
    return { kind: "error" };
  }

  const refreshError = refreshFailed(query);

  return isEmpty(query.data) ? { kind: "empty", refreshError } : { kind: "content", refreshError };
}

export type LoadFailure = {
  message: string;
  // The device could not reach the server at all (as opposed to a server
  // answer or a timeout), so the wording can point at the connection.
  offline: boolean;
};

export function describeLoadFailure(error: unknown, fallback: string): LoadFailure {
  return {
    message: getUserFacingErrorMessage(error, fallback),
    offline: error instanceof ApiError && error.kind === "network",
  };
}

// ---------------------------------------------------------------- wording

export const QUERY_COPY = {
  refreshFailed: (what: string): string => `Could not refresh ${what}. Showing what was loaded earlier.`,
  partialFailed: (what: string): string => `Could not load ${what}.`,
  loadFailed: (what: string): string => `Unable to load ${what}.`,
  empty: (what: string): string => `No ${what} yet.`,
} as const;

// -------------------------------------------------------- accessibility

export type RetryA11y = {
  accessibilityRole: "button";
  accessibilityLabel: string;
  accessibilityState: { disabled: boolean; busy: boolean };
};

export const retryA11y = (what: string, retrying: boolean): RetryA11y => ({
  accessibilityRole: "button",
  accessibilityLabel: retrying ? `Retrying ${what}` : `Retry loading ${what}`,
  accessibilityState: { disabled: retrying, busy: retrying },
});

export type LoadingA11y = { accessible: true; accessibilityRole: "progressbar"; accessibilityLabel: string };

export const loadingA11y = (what: string): LoadingA11y => ({
  accessible: true,
  accessibilityRole: "progressbar",
  accessibilityLabel: `Loading ${what}`,
});
