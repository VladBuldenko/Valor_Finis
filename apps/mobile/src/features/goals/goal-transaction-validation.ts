import { validateGoalDecimalAmount } from "./goal-amount-validation";

export type GoalTransactionFormValues = {
  amount: string;
  description: string;
};

// Matches the backend's GoalTransactionCreate.description max_length
// (services/api/app/modules/goals/goal_transaction_schemas.py).
const MAX_DESCRIPTION_LENGTH = 255;

/**
 * Validates a contribution/withdrawal form before submission.
 * First-error-wins, returns null when valid. The amount check is shared
 * with Goal target_amount validation (goal-amount-validation.ts) -- both
 * follow the same backend decimal contract. Withdrawal-vs-balance
 * sufficiency is intentionally never checked here: the backend is the sole
 * authority (409 on an over-limit withdrawal), so this never duplicates
 * that arithmetic client-side.
 */
export function validateGoalTransactionForm(
  values: GoalTransactionFormValues,
): string | null {
  const amountError = validateGoalDecimalAmount(values.amount, "Amount");

  if (amountError) {
    return amountError;
  }

  if (values.description.trim().length > MAX_DESCRIPTION_LENGTH) {
    return `Description must be ${MAX_DESCRIPTION_LENGTH} characters or fewer.`;
  }

  return null;
}
