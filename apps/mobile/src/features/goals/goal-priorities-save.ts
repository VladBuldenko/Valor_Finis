// Framework-free save orchestration for the Goal Priorities editor
// (VF-020D4). The screen supplies the network call, the cache writer and the
// failure reader; keeping this free of React and the HTTP client makes the
// success / stale-409 / transient-error contract testable with fakes.
//
// Contract:
// - exactly ONE reorder request per call, never retried automatically;
// - 200: the response (complete canonical list, archived included) replaces
//   the Goals cache as is - no refetch, no invalidation of anything else;
// - 409: the non-archived set changed (or an archived id was sent); nothing
//   is retried or merged, the authoritative list is refetched and the caller
//   resets its draft;
// - anything else: nothing is written to the cache and the local draft stays.

import type { Goal } from "./goal.types";

export const STALE_GOALS_MESSAGE =
  "Goals changed while you were editing. The latest order has been loaded.";
export const SAVE_FAILED_MESSAGE =
  "Unable to save the new order. Your changes are kept; please try again.";

export type GoalPrioritySaveOutcome =
  | { kind: "saved"; goals: Goal[] }
  | { kind: "stale"; goals: Goal[] | null; message: string }
  | { kind: "error"; message: string };

export type GoalPrioritySaveDependencies = {
  updateGoalPriorities: (goalIds: string[]) => Promise<Goal[]>;
  replaceGoalsCache: (goals: Goal[]) => void;
  refetchGoals: () => Promise<Goal[] | null>;
  readFailureStatus: (error: unknown) => number | null;
};

export async function saveGoalPriorities(
  goalIds: readonly string[],
  dependencies: GoalPrioritySaveDependencies,
): Promise<GoalPrioritySaveOutcome> {
  let goals: Goal[];

  try {
    goals = await dependencies.updateGoalPriorities([...goalIds]);
  } catch (error) {
    if (dependencies.readFailureStatus(error) === 409) {
      let refreshed: Goal[] | null = null;

      try {
        refreshed = await dependencies.refetchGoals();
      } catch {
        // The controlled message is still shown; the screen keeps showing
        // the (now known to be stale) cache and will refetch on its own.
      }

      return { kind: "stale", goals: refreshed, message: STALE_GOALS_MESSAGE };
    }

    return { kind: "error", message: SAVE_FAILED_MESSAGE };
  }

  dependencies.replaceGoalsCache(goals);

  return { kind: "saved", goals };
}
