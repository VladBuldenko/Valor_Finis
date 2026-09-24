import { validateAccountDecimalAmount } from "./account-amount-validation";

export type AccountTransactionFormValues = {
  amount: string;
  description: string;
};

// Matches the backend's AccountTransactionCreate.description max_length
// (services/api/app/modules/accounts/account_transaction_schemas.py).
const MAX_DESCRIPTION_LENGTH = 500;

/**
 * Validates a manual adjustment form before submission.
 * First-error-wins, returns null when valid, mirroring
 * ../goals/goal-transaction-validation.ts. amount is always positive here
 * -- direction (credit/debit) carries the sign as its own separate field,
 * never accepted as part of the amount string (see account-detail-screen.tsx's
 * segmented direction toggle). Archived-account rejection is intentionally
 * never checked here: the backend is the sole authority (409), so this
 * never duplicates that rule client-side.
 */
export function validateAccountTransactionForm(
  values: AccountTransactionFormValues,
): string | null {
  const amountError = validateAccountDecimalAmount(values.amount, "Amount");

  if (amountError) {
    return amountError;
  }

  if (values.description.trim().length > MAX_DESCRIPTION_LENGTH) {
    return `Description must be ${MAX_DESCRIPTION_LENGTH} characters or fewer.`;
  }

  return null;
}
