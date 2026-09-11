import type { GoalStatus } from "./goal.types";

export type GoalEditFormValues = {
  name: string;
  targetAmount: string;
  currentAmount: string;
  targetDate: string;
  status: GoalStatus;
};

const GOAL_STATUSES: GoalStatus[] = ["active", "completed", "archived"];

/**
 * Validates goal edit form input.
 * Kept as its own function rather than extending goal-validation.ts's
 * validateGoalForm (Create Goal's validator): Edit Goal validates two
 * fields Create Goal never exposes (current_amount, status) plus a
 * cross-field amount check, so duplicating the shared name/target-amount/
 * target-date rules here is simpler than coupling the two forms' validation
 * together (mirrors how Budget keeps its own validation simple). First-
 * error-wins, returns null when valid.
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

  const numericTargetAmount = Number(
    values.targetAmount.trim().replace(",", "."),
  );

  if (!Number.isFinite(numericTargetAmount) || numericTargetAmount <= 0) {
    return "Target amount must be greater than zero.";
  }

  const numericCurrentAmount = Number(
    values.currentAmount.trim().replace(",", "."),
  );

  if (!Number.isFinite(numericCurrentAmount) || numericCurrentAmount < 0) {
    return "Saved so far must be zero or greater.";
  }

  // Local pre-check for the backend's cross-field invariant (current_amount
  // must not exceed target_amount). Checking it here against the form's
  // final values keeps the backend's 400 GoalInvalidAmountError path rare in
  // practice -- see goal-edit-screen.tsx's onError for the fallback message
  // if it still occurs (e.g. a race with a concurrent edit).
  if (numericCurrentAmount > numericTargetAmount) {
    return "Saved so far must not exceed the target amount.";
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
