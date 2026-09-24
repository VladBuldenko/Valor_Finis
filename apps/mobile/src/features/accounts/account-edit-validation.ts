import type { AccountType } from "./account.types";

const ACCOUNT_TYPES: AccountType[] = ["checking", "savings", "cash"];

export type AccountEditFormValues = {
  name: string;
  type: AccountType;
  currency: string;
};

// Matches the backend's AccountBase.name max_length.
const MAX_NAME_LENGTH = 120;

/**
 * Validates Account edit form input.
 * Kept as its own function rather than extending account-validation.ts's
 * validateAccountForm (Create Account's validator): Edit Account never
 * exposes opening_balance/opening_balance_date (those are create-time-only
 * concepts -- see ../goals/goal-edit-validation.ts's identical rationale
 * for why Edit Goal keeps its own separate validator). status is
 * intentionally NOT part of this form at all -- Archive/Reactivate is a
 * dedicated lifecycle action on Account detail, never a field in this
 * generic metadata edit (see account-detail-screen.tsx). First-error-wins,
 * returns null when valid.
 */
export function validateAccountEditForm(
  values: AccountEditFormValues,
): string | null {
  const trimmedName = values.name.trim();

  if (!trimmedName) {
    return "Name is required.";
  }

  if (trimmedName.length > MAX_NAME_LENGTH) {
    return `Name must be ${MAX_NAME_LENGTH} characters or fewer.`;
  }

  if (!ACCOUNT_TYPES.includes(values.type)) {
    return "Type must be Checking, Savings, or Cash.";
  }

  const normalizedCurrency = values.currency.trim().toUpperCase();

  if (!/^[A-Z]{3}$/.test(normalizedCurrency)) {
    return "Currency must be exactly 3 letters.";
  }

  return null;
}
