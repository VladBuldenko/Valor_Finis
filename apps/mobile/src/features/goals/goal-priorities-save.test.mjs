// Focused tests for goal-priorities-save.ts (VF-020D4) with fakes: exactly one
// request per save, success replaces the cache with the exact response, a 409
// refetches without retrying or merging, transient failures keep the cache.
//   node --experimental-strip-types --test src/features/goals/goal-priorities-save.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  SAVE_FAILED_MESSAGE,
  STALE_GOALS_MESSAGE,
  saveGoalPriorities,
} from "./goal-priorities-save.ts";

const RESPONSE = [
  { id: "b", status: "completed", priority_rank: 1 },
  { id: "a", status: "active", priority_rank: 2 },
  { id: "z", status: "archived", priority_rank: null },
];

function fakes(overrides = {}) {
  const calls = { update: [], replace: [], refetch: 0 };

  return {
    calls,
    dependencies: {
      updateGoalPriorities: async (ids) => {
        calls.update.push(ids);
        return RESPONSE;
      },
      replaceGoalsCache: (goals) => calls.replace.push(goals),
      refetchGoals: async () => {
        calls.refetch += 1;
        return [{ id: "fresh" }];
      },
      readFailureStatus: (error) => error?.status ?? null,
      ...overrides,
    },
  };
}

test("save sends exactly one request with the complete ordered ids", async () => {
  const { calls, dependencies } = fakes();

  const outcome = await saveGoalPriorities(["b", "a"], dependencies);

  assert.equal(outcome.kind, "saved");
  assert.equal(calls.update.length, 1);
  assert.deepEqual(calls.update[0], ["b", "a"]);
});

test("success replaces the cache with the exact response, archived included, and refetches nothing", async () => {
  const { calls, dependencies } = fakes();

  const outcome = await saveGoalPriorities(["b", "a"], dependencies);

  assert.equal(calls.replace.length, 1);
  assert.strictEqual(calls.replace[0], RESPONSE);
  assert.deepEqual(calls.replace[0].map((goal) => goal.id), ["b", "a", "z"]);
  assert.equal(calls.refetch, 0);
  assert.strictEqual(outcome.goals, RESPONSE);
});

test("a 409 refetches the authoritative list, shows the controlled message and is never retried", async () => {
  const updates = [];
  const { calls, dependencies } = fakes({
    updateGoalPriorities: async (ids) => {
      updates.push(ids);
      throw Object.assign(new Error("API request failed: 409 {...}"), { status: 409 });
    },
  });

  const outcome = await saveGoalPriorities(["a", "b"], dependencies);

  assert.equal(outcome.kind, "stale");
  assert.equal(outcome.message, STALE_GOALS_MESSAGE);
  assert.equal(outcome.message, "Goals changed while you were editing. The latest order has been loaded.");
  assert.deepEqual(outcome.goals, [{ id: "fresh" }]);
  assert.equal(updates.length, 1);          // not retried
  assert.equal(calls.refetch, 1);
  assert.equal(calls.replace.length, 0);    // the stale draft is never written to the cache
});

test("a 409 whose refetch also fails still returns the controlled stale outcome", async () => {
  const { dependencies } = fakes({
    updateGoalPriorities: async () => {
      throw Object.assign(new Error("409"), { status: 409 });
    },
    refetchGoals: async () => {
      throw new Error("offline");
    },
  });

  const outcome = await saveGoalPriorities(["a"], dependencies);

  assert.equal(outcome.kind, "stale");
  assert.equal(outcome.goals, null);
});

test("network and 5xx failures keep the cache untouched and are retryable", async () => {
  for (const status of [null, 500, 503]) {
    const { calls, dependencies } = fakes({
      updateGoalPriorities: async () => {
        throw Object.assign(new Error("boom"), { status });
      },
    });

    const outcome = await saveGoalPriorities(["a", "b"], dependencies);

    assert.equal(outcome.kind, "error");
    assert.equal(outcome.message, SAVE_FAILED_MESSAGE);
    assert.equal(calls.replace.length, 0);
    assert.equal(calls.refetch, 0);
  }
});

test("the controlled messages never expose raw backend text", () => {
  for (const message of [STALE_GOALS_MESSAGE, SAVE_FAILED_MESSAGE]) {
    assert.equal(message.includes("API request failed"), false);
    assert.equal(message.includes("{"), false);
  }
});
