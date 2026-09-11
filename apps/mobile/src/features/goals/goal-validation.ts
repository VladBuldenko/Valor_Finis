export type GoalFormValues = {
  name: string;
  targetAmount: string;
  targetDate: string;
};

/**
 * Validates goal create form input.
 * Mirrors the client-side rules used for budget creation (see
 * budget-validation.ts): first-error-wins, returns null when valid. The
 * 150-character cap on name matches the backend's GoalCreate.name
 * max_length; target date is optional but must be YYYY-MM-DD when present.
 */
export function validateGoalForm(values: GoalFormValues): string | null {
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

  const trimmedTargetDate = values.targetDate.trim();

  if (trimmedTargetDate && !/^\d{4}-\d{2}-\d{2}$/.test(trimmedTargetDate)) {
    return "Target date must use YYYY-MM-DD format.";
  }

  return null;
}
