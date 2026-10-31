// VF-020F2 (M08): the advisory minimum-floor warning of a manual reservation.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { QueryClient } from "@tanstack/react-query";

import { json, makeHarness } from "../../api/api-test-support.ts";
import { findForbiddenCopy } from "../financial-rules/financial-rule-forbidden-copy.ts";
import { invalidateGoalTransactionQueries } from "./goal-cache.ts";
import {
  FLOOR_WARNING_TITLE,
  buildFloorWarningMessage,
  findFloorWarning,
  handleGoalTransactionSuccess,
} from "./goal-transaction-warning.ts";
import type { GoalTransactionCreated, GoalTransactionFloorWarning } from "./goal.types.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const USER = "user-1";
const GOAL = "goal-1";

const warning: GoalTransactionFloorWarning = {
  code: "minimum_unallocated_floor",
  minimum_unallocated_floor: "500.00",
  projected_reservable_amount: "350.00",
  projected_rule_capacity: "-250.00",
};

const created = (over: Partial<GoalTransactionCreated> = {}): GoalTransactionCreated => ({
  id: "t1", goal_id: GOAL, user_id: USER, type: "contribution", amount: "100.00",
  description: null, created_at: "2026-11-01T00:00:00Z", currency: "EUR",
  effective_date: "2026-11-01", client_request_id: "req-1", account_id: "acc-1", ...over,
});

function run(response: GoalTransactionCreated, isLinked = true) {
  const events: string[] = [];
  const shown: [string, string][] = [];
  const client = new QueryClient();

  client.setQueryData(["goals", USER], []);
  client.setQueryData(["goals", "transactions", USER, GOAL], []);
  client.setQueryData(["analytics", "goal-progress", USER], []);
  client.setQueryData(["accounts", USER], []);
  client.setQueryData(["income", USER], []);

  const done = handleGoalTransactionSuccess({
    response,
    currency: "EUR",
    resetForm: () => { events.push("reset"); },
    presentWarning: (title, message) => { events.push("warn"); shown.push([title, message]); },
    invalidate: async () => {
      events.push("invalidate");
      await invalidateGoalTransactionQueries(client, USER, GOAL, isLinked);
    },
  });

  return { done, events, shown, client };
}

const stale = (client: QueryClient, key: readonly unknown[]) => client.getQueryState(key)?.isInvalidated === true;

describe("backend contract", () => {
  it("matches the backend warning schema fields", () => {
    const source = readFileSync(
      join(HERE, "../../../../../services/api/app/modules/goals/goal_transaction_schemas.py"), "utf8");
    const block = source.slice(source.indexOf("class GoalTransactionFloorWarning"), source.indexOf("class GoalTransactionCreatedResponse"));

    for (const field of Object.keys(warning)) {
      assert.match(block, new RegExp(`^    ${field}\\b`, "m"), field);
    }

    assert.match(source, /warnings: list\[GoalTransactionFloorWarning\]/);
  });
});

describe("successful linked reservation", () => {
  it("with a floor warning: shows it once, still succeeds, refreshes everything", async () => {
    const t = run(created({ warnings: [warning] }));

    await t.done;
    assert.equal(t.shown.length, 1);
    assert.equal(t.shown[0][0], FLOOR_WARNING_TITLE);
    assert.match(t.shown[0][1], /Your reservation was saved/);
    assert.match(t.shown[0][1], /350\.00 EUR/);
    assert.match(t.shown[0][1], /500\.00 EUR/);
    assert.match(t.shown[0][1], /-250\.00 EUR/);
    for (const key of [["goals", USER], ["goals", "transactions", USER, GOAL], ["analytics", "goal-progress", USER], ["accounts", USER]]) {
      assert.ok(stale(t.client, key), JSON.stringify(key));
    }
    assert.ok(!stale(t.client, ["income", USER]));
  });

  it("without warnings: no alert, same refresh", async () => {
    const t = run(created({ warnings: [] }));

    await t.done;
    assert.deepEqual(t.shown, []);
    assert.ok(stale(t.client, ["accounts", USER]));
  });

  it("an older response without the field shows no warning", async () => {
    const t = run(created());

    await t.done;
    assert.deepEqual(t.shown, []);
  });

  it("201 and the idempotent 200 replay (identical body) behave identically", async () => {
    const first = run(created({ warnings: [warning] }));
    const replay = run(created({ warnings: [warning] }));

    await Promise.all([first.done, replay.done]);
    assert.deepEqual(replay.shown, first.shown);
    assert.deepEqual(replay.events, first.events);
  });
});

describe("tracked contribution", () => {
  it("has no warning and does not refresh Accounts", async () => {
    const t = run(created({ account_id: null, warnings: [] }), false);

    await t.done;
    assert.deepEqual(t.shown, []);
    assert.ok(stale(t.client, ["goals", USER]));
    assert.ok(!stale(t.client, ["accounts", USER]));
  });
});

describe("the warning is advisory and comes only from the backend", () => {
  it("is presented BEFORE the refetch finishes, and the form is already reset", async () => {
    const t = run(created({ warnings: [warning] }));

    assert.deepEqual(t.events.slice(0, 3), ["reset", "warn", "invalidate"]);
    await t.done;
  });

  it("a slow or failing refresh cannot swallow the warning", async () => {
    const shown: string[] = [];

    await assert.rejects(
      handleGoalTransactionSuccess({
        response: created({ warnings: [warning] }),
        currency: "EUR",
        resetForm: () => undefined,
        presentWarning: (title) => { shown.push(title); },
        invalidate: async () => { throw new Error("refetch failed"); },
      }),
    );
    assert.deepEqual(shown, [FLOOR_WARNING_TITLE]);
  });

  it("amounts never decide: a warning is shown whatever the numbers say, and none is invented", () => {
    // projected reservable ABOVE the floor yet the backend sent a warning: shown.
    const odd = { ...warning, projected_reservable_amount: "9999.00" };

    assert.deepEqual(findFloorWarning({ warnings: [odd] }), odd);
    // numbers far below any floor but no warning from the backend: none.
    assert.equal(findFloorWarning({ warnings: [] }), null);
    assert.equal(findFloorWarning({}), null);
  });

  it("ignores unknown warning codes and malformed lists", () => {
    const unknown = { ...warning, code: "something_else" } as unknown as GoalTransactionFloorWarning;

    assert.equal(findFloorWarning({ warnings: [unknown] }), null);
    assert.equal(findFloorWarning({ warnings: null as unknown as undefined }), null);
  });

  it("the success path has no way to send a request, and the warning causes no second POST", async () => {
    const h = makeHarness({ respond: async () => json(201, created({ warnings: [warning] })) });
    const response = await h.transport.request<GoalTransactionCreated>("/api/v1/goals/g/transactions", {
      method: "POST",
      body: "{}",
    });
    const t = run(response);

    await t.done;
    assert.equal(h.calls.length, 1);
    assert.equal(h.calls[0].init.method, "POST");
  });
});

describe("terminology", () => {
  it("message and title contain no forbidden wording and never claim a bank movement", () => {
    const message = buildFloorWarningMessage(warning, "EUR");

    assert.deepEqual(findForbiddenCopy(message), []);
    assert.deepEqual(findForbiddenCopy(FLOOR_WARNING_TITLE), []);
    assert.match(message, /guide, not a limit/);
    assert.match(message, /Account balance did not change/);
    assert.doesNotMatch(message, /safe to spend|total balance|transfer|deposit/i);
  });
});
