// VF-020F4 acceptance cases 1-14 for the Dashboard / Inbox attention indicator.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import {
  deriveInboxIndicator,
  inboxIndicatorPresentation,
  isAlertActionable,
  isProposalActionable,
  sourceStateFromQuery,
  type BoundedPages,
  type IndicatorInput,
  type SourceState,
} from "./inbox-data.ts";
import { findForbiddenCopy } from "./financial-rule-forbidden-copy.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const NOW = Date.parse("2026-11-01T12:00:00Z");
const FUTURE = "2026-11-05T00:00:00Z";
const PAST = "2026-10-30T00:00:00Z";

type P = { status: "awaiting_confirmation" | "executed" | "expired" | "rejected" | "cancelled" | "executed_partial"; expires_at: string };
type A = { acknowledged_at: string | null };

const open: P = { status: "awaiting_confirmation", expires_at: FUTURE };
const unackedAlert: A = { acknowledged_at: null };

const done = <T,>(items: T[], over: Partial<SourceState<T>> = {}): SourceState<T> => ({ status: "success", items, complete: true, available: true, ...over });
const failed = <T,>(): SourceState<T> => ({ status: "error", items: [], complete: false, available: true });
const loading = <T,>(): SourceState<T> => ({ status: "loading", items: [], complete: false, available: true });

function input(over: Partial<IndicatorInput> = {}): IndicatorInput {
  return { proposals: done<P>([]), alerts: done<A>([]), evaluation: "not_attempted", now: NOW, ...over };
}

describe("acceptance cases 1-14", () => {
  it("1. actionable loaded item + another FAILED source -> attention", () => {
    assert.equal(deriveInboxIndicator(input({ proposals: done([open]), alerts: failed<A>() })), "attention");
    assert.equal(deriveInboxIndicator(input({ proposals: failed<P>(), alerts: done([unackedAlert]) })), "attention");
  });

  it("2. actionable loaded item + another LOADING source -> attention", () => {
    assert.equal(deriveInboxIndicator(input({ proposals: done([open]), alerts: loading<A>() })), "attention");
    assert.equal(deriveInboxIndicator(input({ proposals: loading<P>(), alerts: done([unackedAlert]) })), "attention");
  });

  it("3. nothing actionable + FAILED source -> unknown", () => {
    assert.equal(deriveInboxIndicator(input({ proposals: failed<P>() })), "unknown");
    assert.equal(deriveInboxIndicator(input({ alerts: failed<A>() })), "unknown");
  });

  it("4. nothing actionable + LOADING source -> unknown", () => {
    assert.equal(deriveInboxIndicator(input({ proposals: loading<P>() })), "unknown");
    assert.equal(deriveInboxIndicator(input({ alerts: loading<A>() })), "unknown");
  });

  it("5. alerts available:false -> unknown, never clear", () => {
    assert.equal(deriveInboxIndicator(input({ alerts: done<A>([], { available: false }) })), "unknown");
  });

  it("6. a next page remains (source incomplete) -> unknown", () => {
    assert.equal(deriveInboxIndicator(input({ proposals: done<P>([], { complete: false }) })), "unknown");
    assert.equal(deriveInboxIndicator(input({ alerts: done<A>([], { complete: false }) })), "unknown");
  });

  it("7. cap reached with more pages -> unknown, and the request count is capped", async () => {
    const { fetchBoundedPages, INBOX_MAX_PAGES } = await import("./inbox-data.ts");
    let requests = 0;
    const result = await fetchBoundedPages(async (offset) => {
      requests += 1;

      return { items: [], total: 1000, limit: 20, offset };
    });

    // Empty pages while more remain cannot advance: stops immediately and is incomplete.
    assert.equal(result.complete, false);
    assert.ok(requests <= INBOX_MAX_PAGES);

    let seen = 0;
    const capped = await fetchBoundedPages(async (offset) => {
      seen += 1;

      return { items: Array.from({ length: 20 }, (_, i) => ({ id: `p${offset + i}` })), total: 1000, limit: 20, offset };
    });

    assert.equal(seen, 3, "exactly one initial page plus two more");
    assert.equal(capped.pagesFetched, 3);
    assert.equal(capped.complete, false);
    assert.equal(
      deriveInboxIndicator(input({ proposals: sourceStateFromQuery({ isError: false, isSuccess: true, data: { ...capped, items: [] } as BoundedPages<P> }) })),
      "unknown",
    );
  });

  it("8. all necessary sources complete and empty -> clear", () => {
    assert.equal(deriveInboxIndicator(input()), "clear");
    assert.equal(deriveInboxIndicator(input({ evaluation: "succeeded" })), "clear");
  });

  it("9. only terminal/expired proposals and acknowledged alerts -> clear when complete", () => {
    const proposals = done<P>([
      { status: "executed", expires_at: FUTURE }, { status: "executed_partial", expires_at: FUTURE },
      { status: "rejected", expires_at: FUTURE }, { status: "cancelled", expires_at: FUTURE },
      { status: "expired", expires_at: PAST }, { status: "awaiting_confirmation", expires_at: PAST },
    ]);
    const alerts = done<A>([{ acknowledged_at: "2026-10-01T00:00:00Z" }]);

    assert.equal(deriveInboxIndicator(input({ proposals, alerts })), "clear");
    // ... but not when completeness is not established.
    assert.equal(deriveInboxIndicator(input({ proposals: { ...proposals, complete: false }, alerts })), "unknown");
  });

  it("10. a failed (or incomplete/pending) evaluation with nothing actionable -> unknown", () => {
    for (const evaluation of ["failed", "incomplete", "pending"] as const) {
      assert.equal(deriveInboxIndicator(input({ evaluation })), "unknown", evaluation);
    }

    // Not attempted does not block clear; attention is unaffected by a failed evaluation.
    assert.equal(deriveInboxIndicator(input({ evaluation: "not_attempted" })), "clear");
    assert.equal(deriveInboxIndicator(input({ proposals: done([open]), evaluation: "failed" })), "attention");
  });

  it("11. last actionable item removed: complete refetch -> clear; failed refetch -> unknown", () => {
    const before = input({ proposals: done([open]) });

    assert.equal(deriveInboxIndicator(before), "attention");
    assert.equal(deriveInboxIndicator({ ...before, proposals: done<P>([]) }), "clear");
    // The refetch failed: stale items are not trusted, nothing is actionable, so unknown.
    const staleAfterFailure = sourceStateFromQuery<P>({ isError: true, isSuccess: false, data: { items: [open], total: 1, complete: true, pagesFetched: 1, available: true } });

    assert.equal(staleAfterFailure.items.length, 0);
    assert.equal(deriveInboxIndicator({ ...before, proposals: staleAfterFailure }), "unknown");
  });

  it("12. a failed execution alone does not create attention (executions are not an input)", () => {
    // The indicator input has no executions field at all.
    assert.deepEqual(Object.keys(input()).sort(), ["alerts", "evaluation", "now", "proposals"]);
    assert.equal(deriveInboxIndicator(input()), "clear");
  });

  it("13. the Dashboard shows no number and no 'unread'", () => {
    const dashboard = readFileSync(join(HERE, "../dashboard/dashboard-screen.tsx"), "utf8");
    const block = dashboard.slice(dashboard.indexOf('<Link href="/inbox"'), dashboard.indexOf('<Link href="/rules"'));

    assert.match(block, /Inbox/);
    assert.match(block, /inboxPresentation\.marker/);
    assert.doesNotMatch(block, /unread|\.length|count|total/i);

    for (const state of ["attention", "clear", "unknown"] as const) {
      const { marker, accessibilityLabel } = inboxIndicatorPresentation(state);

      assert.doesNotMatch(marker + accessibilityLabel, /\d|unread/i);
      assert.deepEqual(findForbiddenCopy(marker + accessibilityLabel), []);
    }
  });

  it("14. accessible names differ per state, and Dashboard and Inbox agree from the same query data", () => {
    const names = (["attention", "clear", "unknown"] as const).map((state) => inboxIndicatorPresentation(state));

    assert.equal(new Set(names.map((entry) => entry.accessibilityLabel)).size, 3);
    assert.equal(new Set(names.map((entry) => entry.marker)).size, 3);
    // Text, not colour: every marker is words.
    assert.ok(names.every((entry) => /^[A-Za-z ]+$/.test(entry.marker)));

    // Both surfaces call the one hook and the one presenter; neither derives alone.
    const dashboard = readFileSync(join(HERE, "../dashboard/dashboard-screen.tsx"), "utf8");
    const inbox = readFileSync(join(HERE, "inbox-screen.tsx"), "utf8");

    for (const source of [dashboard, inbox]) {
      assert.match(source, /useInboxData\(\)/);
      assert.match(source, /inboxIndicatorPresentation\(/);
      assert.doesNotMatch(source, /deriveInboxIndicator/);
    }

    // The same query data gives the same answer.
    const data = { isError: false, isSuccess: true, data: { items: [open], total: 1, complete: true, pagesFetched: 1, available: true } };
    const a = deriveInboxIndicator(input({ proposals: sourceStateFromQuery<P>(data) }));
    const b = deriveInboxIndicator(input({ proposals: sourceStateFromQuery<P>(data) }));

    assert.equal(a, b);
  });
});

describe("indicator details", () => {
  it("an open proposal past its expiry, or with an unreadable expiry, is not actionable", () => {
    assert.equal(isProposalActionable({ status: "awaiting_confirmation", expires_at: PAST }, NOW), false);
    assert.equal(isProposalActionable({ status: "awaiting_confirmation", expires_at: "garbage" }, NOW), false);
    assert.equal(isProposalActionable(open, NOW), true);
    assert.equal(isAlertActionable(unackedAlert), true);
  });

  it("unavailable alerts cannot create attention even with items", () => {
    assert.equal(deriveInboxIndicator(input({ alerts: done([unackedAlert], { available: false }) })), "unknown");
  });

  it("a source in error or loading hands over no items", () => {
    assert.deepEqual(sourceStateFromQuery<P>({ isError: false, isSuccess: false, data: undefined }), { status: "loading", items: [], complete: false, available: true });
  });
});
