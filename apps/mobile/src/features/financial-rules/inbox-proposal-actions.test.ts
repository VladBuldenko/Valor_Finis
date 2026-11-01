import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { ApiError } from "../../api/api-error.ts";
import { COPY } from "./financial-rule-copy.ts";
import type { ProposalDecision } from "./financial-rule-presentation.ts";
import { CONFIRM_DIALOG, HOLD_EXPLANATION, REJECT_DIALOG, decideProposal } from "./inbox-proposal-actions.ts";
import { PROPOSAL_STATUSES, type ProposalStatus, type RuleProposal } from "./financial-rule.types.ts";
import { findForbiddenCopy } from "./financial-rule-forbidden-copy.ts";

const proposal = (status: ProposalStatus): RuleProposal => ({
  id: "p1", rule_id: "r1", rule_name: "Save", rule_version: 1, status, reason_code: null, partial: status === "executed_partial",
  hold_sequence: 1, expires_at: "2026-11-05T00:00:00Z", created_at: "t", decided_at: null, source_id: "s", source_amount: "3000.00",
  source_currency: "EUR", source_received_at: "2026-11-01", account_id: "a", currency: "EUR", planned_total: "450.00",
  confirm_capacity: null, items: [],
});

function setup(over: { send?: () => Promise<RuleProposal>; refetch?: () => Promise<RuleProposal>; current?: boolean; decision?: ProposalDecision } = {}) {
  const log = { sends: 0, refetches: 0, invalidated: [] as string[][] };
  const run = () =>
    decideProposal({
      decision: over.decision ?? "confirm",
      userId: "user-a",
      send: async () => { log.sends += 1; return (over.send ?? (async () => proposal("executed")))(); },
      refetch: async () => { log.refetches += 1; return (over.refetch ?? (async () => proposal("awaiting_confirmation")))(); },
      isCurrent: () => over.current ?? true,
      invalidate: (keys) => { log.invalidated = keys.map((key) => key.map(String)); },
    });

  return { log, run };
}

const http = (status: number, code: string | null) => new ApiError({ kind: "http", status, code, message: `API request failed: ${status} {}` });
const ambiguous = () => new ApiError({ kind: "timeout", message: "x" });
const families = (keys: string[][]) => keys.map((key) => key[0]);

describe("every returned status decides the outcome", () => {
  const expected: Record<ProposalStatus, { confirmMatches: boolean; rejectMatches: boolean; notSuccess: boolean }> = {
    executed: { confirmMatches: true, rejectMatches: false, notSuccess: false },
    executed_partial: { confirmMatches: true, rejectMatches: false, notSuccess: false },
    rejected: { confirmMatches: false, rejectMatches: true, notSuccess: true },
    expired: { confirmMatches: false, rejectMatches: false, notSuccess: true },
    cancelled: { confirmMatches: false, rejectMatches: false, notSuccess: true },
    awaiting_confirmation: { confirmMatches: false, rejectMatches: false, notSuccess: true },
  };

  for (const status of PROPOSAL_STATUSES) {
    it(`${status}: HTTP 200 is not the result, the status is`, async () => {
      for (const decision of ["confirm", "reject"] as const) {
        const { run } = setup({ send: async () => proposal(status), decision });
        const result = await run();

        assert.equal(result.kind, "decided");

        if (result.kind === "decided") {
          assert.equal(result.outcome.status, status);
          assert.equal(result.outcome.matchesRequest, decision === "confirm" ? expected[status].confirmMatches : expected[status].rejectMatches);

          if (expected[status].notSuccess) {
            assert.doesNotMatch(result.outcome.message, /^Reserved|Partly reserved/);
          }
        }
      }
    });
  }

  it("a confirm that returns expired / cancelled / rejected is never shown as a reservation", async () => {
    for (const status of ["expired", "cancelled", "rejected"] as const) {
      const result = await setup({ send: async () => proposal(status) }).run();

      assert.equal(result.kind === "decided" && /Nothing was reserved/.test(result.outcome.message), true, status);
    }
  });
});

describe("invalidation follows the returned status", () => {
  it("executed / executed_partial refresh Goals, Goal Progress and Accounts", async () => {
    for (const status of ["executed", "executed_partial"] as const) {
      const { log, run } = setup({ send: async () => proposal(status) });

      await run();
      assert.deepEqual(families(log.invalidated), ["rule-proposals", "rule-executions", "goals", "analytics", "accounts"], status);
    }
  });

  it("rejected / expired / cancelled refresh proposals, executions and Accounts only", async () => {
    for (const status of ["rejected", "expired", "cancelled"] as const) {
      const { log, run } = setup({ send: async () => proposal(status), decision: "reject" });

      await run();
      assert.deepEqual(families(log.invalidated), ["rule-proposals", "rule-executions", "accounts"], status);
    }
  });

  it("never touches Income, Expenses, Budgets or Transfers", async () => {
    const { log, run } = setup();

    await run();
    assert.ok(!families(log.invalidated).some((family) => ["income", "expenses", "budgets", "account-transfers"].includes(family)));
    assert.ok(log.invalidated.every((key) => key.includes("user-a")));
  });
});

describe("idempotent replay and duplicates", () => {
  it("replaying a confirm on an already executed proposal shows the stored outcome with one POST", async () => {
    const { log, run } = setup({ send: async () => proposal("executed") });
    const result = await run();

    assert.equal(log.sends, 1);
    assert.equal(result.kind === "decided" && result.outcome.status, "executed");
  });

  it("rejecting an already rejected proposal is the same stored outcome", async () => {
    const result = await setup({ send: async () => proposal("rejected"), decision: "reject" }).run();

    assert.equal(result.kind === "decided" && result.outcome.matchesRequest, true);
  });

  it("every path sends exactly one POST (never resends), whatever fails", async () => {
    const errors = [http(409, "rule_proposal_stale"), ambiguous(), http(404, "rule_proposal_not_found"), http(500, null), new Error("x")];

    for (const error of errors) {
      const { log, run } = setup({ send: async () => { throw error; } });

      await run();
      assert.equal(log.sends, 1, String(error));
    }
  });
});

describe("stale 409 and ambiguous outcomes: authoritative refetch first", () => {
  it("stale: refetches (one GET), shows the cancelled state, refreshes related data", async () => {
    const { log, run } = setup({ send: async () => { throw http(409, "rule_proposal_stale"); }, refetch: async () => proposal("cancelled") });
    const result = await run();

    assert.equal(log.refetches, 1);
    assert.equal(result.kind, "stale");
    assert.equal(result.kind === "stale" && result.proposal?.status, "cancelled");
    assert.match(result.kind === "stale" ? result.message : "", /Nothing was reserved/);
    assert.deepEqual(families(log.invalidated), ["rule-proposals", "rule-executions", "accounts"]);
  });

  it("stale with a failing refetch still reports stale and refreshes", async () => {
    const { log, run } = setup({ send: async () => { throw http(409, "rule_proposal_stale"); }, refetch: async () => { throw new Error("offline"); } });
    const result = await run();

    assert.equal(result.kind === "stale" && result.proposal, null);
    assert.ok(log.invalidated.length > 0);
  });

  it("timeout whose refetch shows executed -> resolved to the real outcome", async () => {
    const { log, run } = setup({ send: async () => { throw ambiguous(); }, refetch: async () => proposal("executed") });
    const result = await run();

    assert.equal(result.kind, "unknown_resolved");
    assert.equal(result.kind === "unknown_resolved" && result.outcome.status, "executed");
    assert.equal(log.sends, 1);
    assert.ok(families(log.invalidated).includes("goals"));
  });

  it("timeout whose refetch still shows awaiting -> 'unknown', full refresh, no claim of success or failure", async () => {
    const { log, run } = setup({ send: async () => { throw ambiguous(); }, refetch: async () => proposal("awaiting_confirmation") });
    const result = await run();

    assert.equal(result.kind, "unknown_pending");
    assert.equal(result.kind === "unknown_pending" && result.message, COPY.outcomeUnknown);
    assert.ok(families(log.invalidated).includes("goals"));
  });

  it("timeout and a failed refetch -> unknown, nothing claimed", async () => {
    const result = await setup({ send: async () => { throw ambiguous(); }, refetch: async () => { throw ambiguous(); } }).run();

    assert.equal(result.kind, "unknown_pending");
    assert.equal(result.kind === "unknown_pending" && result.proposal, null);
  });

  it("a 5xx is treated as ambiguous; a definite 4xx is a plain failure", async () => {
    assert.equal((await setup({ send: async () => { throw http(500, null); } }).run()).kind, "unknown_pending");

    const notFound = await setup({ send: async () => { throw http(404, "rule_proposal_not_found"); } }).run();

    assert.equal(notFound.kind, "failed");
    assert.equal(notFound.kind === "failed" && notFound.info.category, "not_found");
  });
});

describe("session ownership", () => {
  it("applies no invalidation when the session is gone by the time the answer arrives", async () => {
    const { log, run } = setup({ current: false });
    const result = await run();

    assert.equal(result.kind, "decided");
    assert.deepEqual(log.invalidated, []);
  });

  it("the plan is built for the starting user only", async () => {
    const { log, run } = setup();

    await run();
    assert.ok(log.invalidated.every((key) => key[1] === "user-a" || key.includes("user-a")));
    assert.ok(!log.invalidated.some((key) => key.includes("user-b")));
  });
});

describe("terminology", () => {
  it("dialogs and the hold explanation follow C2/C5 and the forbidden-copy rules", () => {
    for (const text of [CONFIRM_DIALOG.title, CONFIRM_DIALOG.message, REJECT_DIALOG.title, REJECT_DIALOG.message, HOLD_EXPLANATION]) {
      assert.deepEqual(findForbiddenCopy(text), [], text);
    }

    assert.match(CONFIRM_DIALOG.message, /does not move any money in your bank/);
    assert.match(HOLD_EXPLANATION, /Nothing is reserved until you confirm/);
  });
});
