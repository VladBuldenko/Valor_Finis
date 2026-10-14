// Pure helpers for the Goal Priorities editor (VF-020D4). Nothing here knows
// about React, the network or the cache, so it runs under the Node test
// runner. The editor shows only NON-ARCHIVED Goals (active and completed) in
// the backend's canonical order; the local draft is a plain list of Goal ids
// and is the only thing that decides what a Save sends. Priority is never
// derived from amounts, dates or creation time.

import type { Goal } from "./goal.types";

type GoalIdentity = Pick<Goal, "id" | "status">;

// The user's non-archived Goals in the exact order the backend returned them.
// No sorting is applied: the backend list order is authoritative, including
// for unranked rollout stragglers.
export function getNonArchivedGoals<T extends GoalIdentity>(
  goals: readonly T[],
): T[] {
  return goals.filter((goal) => goal.status !== "archived");
}

// The ordered id list the editor starts from.
export function getBaselineGoalIds(goals: readonly GoalIdentity[]): string[] {
  return getNonArchivedGoals(goals).map((goal) => goal.id);
}

export function areSameOrder(
  first: readonly string[],
  second: readonly string[],
): boolean {
  return (
    first.length === second.length &&
    first.every((id, index) => id === second[index])
  );
}

// Whether the draft differs from the authoritative order (enables Save).
export function isDraftChanged(
  draft: readonly string[],
  baseline: readonly string[],
): boolean {
  return !areSameOrder(draft, baseline);
}

export function canMoveUp(draft: readonly string[], index: number): boolean {
  return index > 0 && index < draft.length;
}

export function canMoveDown(draft: readonly string[], index: number): boolean {
  return index >= 0 && index < draft.length - 1;
}

// Returns a NEW draft with the item at `index` moved one place. An impossible
// move (first up, last down, out of range) returns an unchanged copy. The
// input array is never mutated and there is no wraparound.
export function moveDraftItem(
  draft: readonly string[],
  index: number,
  direction: "up" | "down",
): string[] {
  const next = [...draft];
  const target = direction === "up" ? index - 1 : index + 1;

  if (index < 0 || index >= next.length || target < 0 || target >= next.length) {
    return next;
  }

  [next[index], next[target]] = [next[target], next[index]];

  return next;
}

// Resolves the draft to display. `draft` is null while the user has made no
// local edit. A draft whose id SET no longer equals the baseline's (the Goal
// list changed underneath) is discarded in favor of the baseline instead of
// being merged silently.
export function resolveDraft(
  draft: readonly string[] | null,
  baseline: readonly string[],
): string[] {
  if (draft === null) {
    return [...baseline];
  }

  const baselineSet = new Set(baseline);
  const sameSet =
    draft.length === baseline.length &&
    draft.every((id) => baselineSet.has(id));

  return sameSet ? [...draft] : [...baseline];
}

// Save is possible only with a real change and no request in flight.
export function canSaveDraft(
  draft: readonly string[],
  baseline: readonly string[],
  isPending: boolean,
): boolean {
  return !isPending && isDraftChanged(draft, baseline);
}

// The reorder request (PUT /api/v1/goals/priorities). Kept pure so the exact
// endpoint, method and body are testable: the body is the COMPLETE ordered
// list of non-archived Goal ids (archived ids are never sent) and carries no
// client_request_id - a full-state PUT is naturally idempotent.
export function buildGoalPrioritiesRequest(goalIds: readonly string[]): {
  path: string;
  method: "PUT";
  body: string;
} {
  return {
    path: "/api/v1/goals/priorities",
    method: "PUT",
    body: JSON.stringify({ goal_ids: [...goalIds] }),
  };
}
