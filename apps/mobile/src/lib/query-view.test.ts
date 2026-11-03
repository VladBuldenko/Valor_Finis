// VF-MOB-REFRESH-RETRY: how screens read a query (pure).
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { ApiError } from "../api/api-error.ts";
import {
  NETWORK_ERROR_MESSAGE,
  SERVER_ERROR_MESSAGE,
  TIMEOUT_MESSAGE,
} from "../api/user-facing-error.ts";
import {
  QUERY_COPY,
  boundaryView,
  combinedPhase,
  describeLoadFailure,
  loadingA11y,
  queryPhase,
  refreshFailed,
  retryA11y,
} from "./query-view.ts";

const q = (data: unknown[] | undefined, isError: boolean) => ({ data, isError });
const http = (status: number, body: string) =>
  new ApiError({ kind: "http", message: `API request failed: ${status} ${body}`, status, detail: null, body });

describe("query phase", () => {
  it("loading -> data, loading -> error, and data wins over a later error", () => {
    assert.equal(queryPhase(q(undefined, false)), "loading");
    assert.equal(queryPhase(q([1], false)), "ready");
    assert.equal(queryPhase(q(undefined, true)), "error");
    assert.equal(queryPhase(q([1], true)), "ready", "a failed refresh keeps the data on screen");
  });

  it("an empty array is data, not a failure and not 'loading'", () => {
    assert.equal(queryPhase(q([], false)), "ready");
  });

  it("refreshFailed only with data AND an error", () => {
    assert.equal(refreshFailed(q([1], true)), true);
    assert.equal(refreshFailed(q(undefined, true)), false);
    assert.equal(refreshFailed(q([1], false)), false);
  });

  it("several queries: an error is never hidden behind a spinner", () => {
    assert.equal(combinedPhase([q([1], false), q(undefined, true)]), "error");
    assert.equal(combinedPhase([q(undefined, false), q(undefined, true)]), "error");
    assert.equal(combinedPhase([q([1], false), q(undefined, false)]), "loading");
    assert.equal(combinedPhase([q([1], false), q([], false)]), "ready");
  });
});

describe("what a section shows", () => {
  const empty = (d: unknown[]) => d.length === 0;

  it("loading, error, empty and content are four different views", () => {
    assert.deepEqual(boundaryView(q(undefined, false), empty), { kind: "loading" });
    assert.deepEqual(boundaryView(q(undefined, true), empty), { kind: "error" });
    assert.deepEqual(boundaryView(q([], false), empty), { kind: "empty", refreshError: false });
    assert.deepEqual(boundaryView(q([1], false), empty), { kind: "content", refreshError: false });
  });

  it("a failure with nothing loaded is never an empty list", () => {
    assert.notEqual(boundaryView(q(undefined, true), empty).kind, "empty");
    assert.notEqual(boundaryView(q(undefined, true), empty).kind, "content");
  });

  it("a failed refresh keeps the content (or the genuine empty state) and reports the failure", () => {
    assert.deepEqual(boundaryView(q([1, 2], true), empty), { kind: "content", refreshError: true });
    assert.deepEqual(boundaryView(q([], true), empty), { kind: "empty", refreshError: true });
  });
});

describe("failures are described for the user", () => {
  it("a server error never shows the backend body, URL, trace or token", () => {
    const leaked = http(500, '<html>Traceback (most recent call last): File "/srv/app.py" Bearer abc.def.ghi</html>');
    const failure = describeLoadFailure(leaked, "Unable to load accounts.");

    assert.equal(failure.message, SERVER_ERROR_MESSAGE);
    assert.doesNotMatch(failure.message, /Traceback|srv|Bearer|html/i);
  });

  it("offline is only a network failure; timeouts get their own wording", () => {
    const network = describeLoadFailure(new ApiError({ kind: "network", message: "fetch failed https://x/y?token=1" }), "f");
    const timeout = describeLoadFailure(new ApiError({ kind: "timeout", message: "t" }), "f");

    assert.deepEqual([network.offline, network.message], [true, NETWORK_ERROR_MESSAGE]);
    assert.deepEqual([timeout.offline, timeout.message], [false, TIMEOUT_MESSAGE]);
    assert.doesNotMatch(network.message, /https|token/);
  });

  it("an unrecognised error falls back to the caller's text, never error.message", () => {
    const failure = describeLoadFailure(new Error("secret internal detail"), QUERY_COPY.loadFailed("goals"));

    assert.equal(failure.message, "Unable to load goals.");
    assert.equal(describeLoadFailure("boom", "fallback").message, "fallback");
  });
});

describe("accessibility metadata", () => {
  it("Retry is a button named for what it retries, disabled and busy while it runs", () => {
    assert.deepEqual(retryA11y("goals", false), {
      accessibilityRole: "button",
      accessibilityLabel: "Retry loading goals",
      accessibilityState: { disabled: false, busy: false },
    });
    assert.deepEqual(retryA11y("goals", true).accessibilityState, { disabled: true, busy: true });
    assert.equal(retryA11y("goals", true).accessibilityLabel, "Retrying goals");
  });

  it("loading is a labelled progress indicator", () => {
    assert.deepEqual(loadingA11y("goals"), { accessible: true, accessibilityRole: "progressbar", accessibilityLabel: "Loading goals" });
  });

  it("every section's wording is plain and names the data", () => {
    assert.equal(QUERY_COPY.refreshFailed("accounts"), "Could not refresh accounts. Showing what was loaded earlier.");
    assert.equal(QUERY_COPY.partialFailed("goal progress"), "Could not load goal progress.");
    assert.equal(QUERY_COPY.empty("budgets"), "No budgets yet.");
  });
});
