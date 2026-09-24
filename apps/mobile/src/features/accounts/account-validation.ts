import { validateOpeningBalanceAmount } from "./account-amount-validation";
import type { AccountType } from "./account.types";

const ACCOUNT_TYPES: AccountType[] = ["checking", "savings", "cash"];

export type AccountFormValues = {
  name: string;
  type: AccountType;
  currency: string;
  openingBalance: string;
  openingBalanceDate: string;
};

// Matches the backend's AccountBase.name max_length
// (services/api/app/modules/accounts/account_schemas.py).
const MAX_NAME_LENGTH = 120;

/**
 * Validates Account create form input.
 * First-error-wins, returns null when valid, mirroring
 * ../goals/goal-validation.ts's validateGoalForm shape. currency is
 * validated only for shape here (exactly 3 alphabetic characters) -- the
 * backend is the sole authority on whether it actually accepts a given
 * code. opening_balance is optional and SIGNED (zero is a valid value,
 * not an error -- see validateOpeningBalanceAmount); openingBalanceDate is
 * only meaningful when a non-zero opening balance is actually being sent,
 * but is still shape-validated here whenever it is non-blank so the user
 * gets feedback even if they filled the date before the amount.
 */
export function validateAccountForm(values: AccountFormValues): string | null {
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

  const openingBalanceError = validateOpeningBalanceAmount(
    values.openingBalance,
  );

  if (openingBalanceError) {
    return openingBalanceError;
  }

  const trimmedOpeningBalanceDate = values.openingBalanceDate.trim();

  if (
    trimmedOpeningBalanceDate &&
    !/^\d{4}-\d{2}-\d{2}$/.test(trimmedOpeningBalanceDate)
  ) {
    return "Opening balance date must use YYYY-MM-DD format.";
  }

  return null;
}
