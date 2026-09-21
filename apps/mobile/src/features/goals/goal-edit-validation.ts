import { validateGoalDecimalAmount } from "./goal-amount-validation";
import type { GoalStatus } from "./goal.types";

export type GoalEditFormValues = {
  name: string;
  targetAmount: string;
  targetDate: string;
  status: GoalStatus;
};

const GOAL_STATUSES: GoalStatus[] = ["active", "completed", "archived"];

/**
 * Validates goal edit form input.
 * Kept as its own function rather than extending goal-validation.ts's
 * validateGoalForm (Create Goal's validator): Edit Goal validates a field
 * Create Goal never exposes (status), so duplicating the shared name/
 * target-amount/target-date rules here is simpler than coupling the two
 * forms' validation together (mirrors how Budget keeps its own validation
 * simple). First-error-wins, returns null when valid.
 *
 * current_amount is intentionally NOT part of this form (VF-016F): it is
 * no longer client-writable, so there is no "saved so far" field to
 * validate, and no current-vs-target cross-field check either -- lowering
 * target_amount below the goal's actual (ledger-derived) balance is a
 * valid, allowed state (overfunding), not an error.
 */
export function validateGoalEditForm(
  values: GoalEditFormValues,
): string | null {
  const trimmedName = values.name.trim();

  if (!trimmedName) {
    return "Name is required.";
  }

  if (trimmedName.length > 150) {
    return "Name must be 150 characters or fewer.";
  }

  const targetAmountError = validateGoalDecimalAmount(
    values.targetAmount,
    "Target amount",
  );

  if (targetAmountError) {
    return targetAmountError;
  }

  const trimmedTargetDate = values.targetDate.trim();

  if (trimmedTargetDate && !/^\d{4}-\d{2}-\d{2}$/.test(trimmedTargetDate)) {
    return "Target date must use YYYY-MM-DD format.";
  }

  if (!GOAL_STATUSES.includes(values.status)) {
    return "Status must be Active, Completed, or Archived.";
  }

  return null;
}
