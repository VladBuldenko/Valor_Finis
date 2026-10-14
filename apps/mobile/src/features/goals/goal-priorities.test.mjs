// Focused tests for goal-priorities.ts (VF-020D4): the pure draft/ordering
// logic and the reorder request builder.
//   node --experimental-strip-types --test src/features/goals/goal-priorities.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  areSameOrder,
  buildGoalPrioritiesRequest,
  canMoveDown,
  canMoveUp,
  canSaveDraft,
  getBaselineGoalIds,
  getNonArchivedGoals,
  isDraftChanged,
  moveDraftItem,
  resolveDraft,
} from "./goal-priorities.ts";

function goal(id, status, extra = {}) {
  return { id, status, name: id, priority_rank: null, ...extra };
}

const LIST = [
  goal("a", "active", { priority_rank: 1 }),
  goal("b", "completed", { priority_rank: 2 }),
  goal("x", "active", { priority_rank: null }), // rollout straggler
  goal("z", "archived"),
];

test("initial draft preserves the backend order, keeps completed and drops archived", () => {
  assert.deepEqual(getBaselineGoalIds(LIST), ["a", "b", "x"]);
  assert.deepEqual(getNonArchivedGoals(LIST).map((item) => item.status), ["active", "completed", "active"]);
});

test("a rank-NULL straggler keeps the position the backend gave it (no local sorting)", () => {
  const reversed = [LIST[2], LIST[0], LIST[1], LIST[3]];

  assert.deepEqual(getBaselineGoalIds(reversed), ["x", "a", "b"]);
});

test("ordering ignores amounts, dates and creation time", () => {
  const list = [
    goal("late", "active", { created_at: "2030-01-01", current_amount: "0.00", target_date: "2031-01-01" }),
    goal("early", "active", { created_at: "2020-01-01", current_amount: "999.00", target_date: "2021-01-01" }),
  ];

  assert.deepEqual(getBaselineGoalIds(list), ["late", "early"]);
});

test("first item cannot move up and last item cannot move down", () => {
  const draft = ["a", "b", "c"];

  assert.equal(canMoveUp(draft, 0), false);
  assert.equal(canMoveDown(draft, 2), false);
  assert.equal(canMoveUp(draft, 1), true);
  assert.equal(canMoveDown(draft, 0), true);
  assert.deepEqual(moveDraftItem(draft, 0, "up"), draft);
  assert.deepEqual(moveDraftItem(draft, 2, "down"), draft);
});

test("a middle item swaps exactly once and the input is not mutated", () => {
  const draft = Object.freeze(["a", "b", "c"]);

  assert.deepEqual(moveDraftItem(draft, 1, "up"), ["b", "a", "c"]);
  assert.deepEqual(moveDraftItem(draft, 1, "down"), ["a", "c", "b"]);
  assert.deepEqual([...draft], ["a", "b", "c"]);
});

test("repeated moves produce the expected sequence", () => {
  let draft = ["a", "b", "c", "d"];
  draft = moveDraftItem(draft, 3, "up");   // a b d c
  draft = moveDraftItem(draft, 2, "up");   // a d b c
  draft = moveDraftItem(draft, 1, "up");   // d a b c
  draft = moveDraftItem(draft, 0, "up");   // no-op

  assert.deepEqual(draft, ["d", "a", "b", "c"]);
});

test("changed and unchanged detection", () => {
  assert.equal(isDraftChanged(["a", "b"], ["a", "b"]), false);
  assert.equal(isDraftChanged(["b", "a"], ["a", "b"]), true);
  assert.equal(areSameOrder([], []), true);
  assert.equal(isDraftChanged(["a"], ["a", "b"]), true);
});

test("moving a goal away and back leaves the draft unchanged (Save disabled)", () => {
  const baseline = ["a", "b", "c"];
  const moved = moveDraftItem(baseline, 0, "down");
  const back = moveDraftItem(moved, 1, "up");

  assert.equal(isDraftChanged(moved, baseline), true);
  assert.equal(isDraftChanged(back, baseline), false);
});

test("Save is enabled only for a real change with nothing pending", () => {
  const baseline = ["a", "b"];

  assert.equal(canSaveDraft(baseline, baseline, false), false);
  assert.equal(canSaveDraft(["b", "a"], baseline, false), true);
  assert.equal(canSaveDraft(["b", "a"], baseline, true), false);
});

test("empty and single-goal states never allow Save or movement", () => {
  assert.equal(canSaveDraft([], [], false), false);
  assert.equal(canMoveUp(["a"], 0), false);
  assert.equal(canMoveDown(["a"], 0), false);
  assert.equal(canSaveDraft(["a"], ["a"], false), false);
});

test("resolveDraft: no edit shows the baseline; a draft over a changed set is dropped, not merged", () => {
  assert.deepEqual(resolveDraft(null, ["a", "b"]), ["a", "b"]);
  assert.deepEqual(resolveDraft(["b", "a"], ["a", "b"]), ["b", "a"]);
  assert.deepEqual(resolveDraft(["b", "a"], ["a", "b", "c"]), ["a", "b", "c"]);
  assert.deepEqual(resolveDraft(["b", "a"], ["a", "c"]), ["a", "c"]);
});

test("the request is one PUT to the priorities endpoint with the complete ordered ids", () => {
  const request = buildGoalPrioritiesRequest(["b", "a", "x"]);

  assert.equal(request.method, "PUT");
  assert.equal(request.path, "/api/v1/goals/priorities");
  assert.deepEqual(JSON.parse(request.body), { goal_ids: ["b", "a", "x"] });
  assert.equal("client_request_id" in JSON.parse(request.body), false);
});
