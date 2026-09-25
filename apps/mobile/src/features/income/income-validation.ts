import { INCOME_SOURCES, type IncomeSource } from "./income.types";

export type IncomeFormValues = {
  amount: string;
  currency: string;
  receivedAt: string;
  source: IncomeSource;
  description: string;
};

// Matches the backend's IncomeBase.description max_length
// (services/api/app/modules/income/income_schemas.py).
const MAX_DESCRIPTION_LENGTH = 500;

// Normalizes a decimal money-amount string for submission: trims
// whitespace and converts a comma decimal separator to a point, matching
// the trim/replace(",", ".") convention used across this app's create/
// edit screens. Callers must validate with validateIncomeForm before
// treating the result as safe to send.
export function normalizeIncomeAmount(rawValue: string): string {
  return rawValue.trim().replace(",", ".");
}

// Validates Income's always-positive amount: required, digits with up to
// 2 decimal places, no sign/exponent notation, and not zero. Stays
// string-based throughout -- the value is never parsed into a JavaScript
// Number (CLAUDE.md Decimal-only rule). Mirrors the Account/Goal amount
// validators; the backend remains authoritative (e.g. for its 12-digit
// precision limit).
function validateIncomeAmount(rawValue: string): string | null {
  const normalized = normalizeIncomeAmount(rawValue);

  if (!normalized) {
    return "Amount is required.";
  }

  if (!/^\d+(\.\d{1,2})?$/.test(normalized)) {
    return "Amount must be a positive number with up to 2 decimal places.";
  }

  if (/^0+(\.0+)?$/.test(normalized)) {
    return "Amount must be greater than zero.";
  }

  return null;
}

/**
 * Validates Income create/edit form input. First-error-wins, returns null
 * when valid. Only input shape is checked here: the backend is the sole
 * authority on calendar-date validity, FX availability, future-dated
 * foreign-currency rejection, and Income/Account currency matching.
 */
export function validateIncomeForm(values: IncomeFormValues): string | null {
  const amountError = validateIncomeAmount(values.amount);

  if (amountError) {
    return amountError;
  }

  const normalizedCurrency = values.currency.trim().toUpperCase();

  if (!/^[A-Z]{3}$/.test(normalizedCurrency)) {
    return "Currency must be exactly 3 letters.";
  }

  if (!/^\d{4}-\d{2}-\d{2}$/.test(values.receivedAt.trim())) {
    return "Received date must use YYYY-MM-DD format.";
  }

  if (!INCOME_SOURCES.includes(values.source)) {
    return "Source must be Salary, Freelance, Refund, Gift, or Other.";
  }

  if (values.description.trim().length > MAX_DESCRIPTION_LENGTH) {
    return `Description must be ${MAX_DESCRIPTION_LENGTH} characters or fewer.`;
  }

  return null;
}
