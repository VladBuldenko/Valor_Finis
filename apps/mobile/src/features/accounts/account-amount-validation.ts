// Validates a decimal money-amount string against the shared contract used
// by Account's always-positive amount field (manual adjustment amount):
// positive, up to 2 decimal places, no exponent/negative notation, no
// leading/trailing garbage. Deliberately never parses the value as a
// JavaScript Number (see CLAUDE.md's Decimal-only rule, and the mobile
// financial-string rule already established for Goal -- see
// ../goals/goal-amount-validation.ts) -- both the regex shape check and
// the zero check below stay string-based throughout. Exact mirror of
// validateGoalDecimalAmount.
//
// A comma is normalized to a decimal point first, matching the trim/
// replace(",", ".") convention already used across this app's create/edit
// screens before a value is sent to the backend.
//
// Returns a user-facing error message, or null when the value is valid.
export function validateAccountDecimalAmount(
  rawValue: string,
  fieldLabel: string,
): string | null {
  const normalized = rawValue.trim().replace(",", ".");

  if (!normalized) {
    return `${fieldLabel} is required.`;
  }

  if (!/^\d+(\.\d{1,2})?$/.test(normalized)) {
    return `${fieldLabel} must be a positive number with up to 2 decimal places.`;
  }

  if (isZeroDecimalAmount(normalized)) {
    return `${fieldLabel} must be greater than zero.`;
  }

  return null;
}

// Validates Account's SIGNED opening_balance field: optional (an empty
// value is valid -- the field itself is optional on AccountCreateInput),
// an optional leading "-", digits, and up to 2 decimal places. Unlike
// validateAccountDecimalAmount above, a ZERO value is explicitly VALID
// here -- backend semantics are positive -> credit opening_balance
// transaction, negative -> debit, null/zero -> no transaction at all, so
// zero is a legitimate "no starting balance" input, not an error.
// Never parses the value as a JavaScript Number -- both the shape check
// and the zero check (isZeroDecimalAmount) stay string-based throughout.
//
// Returns a user-facing error message, or null when the value is valid
// (including when it is empty).
export function validateOpeningBalanceAmount(
  rawValue: string,
): string | null {
  const normalized = rawValue.trim().replace(",", ".");

  if (!normalized) {
    return null;
  }

  if (!/^-?\d+(\.\d{1,2})?$/.test(normalized)) {
    return "Opening balance must be a number with up to 2 decimal places.";
  }

  return null;
}

// String-based zero detection for a normalized decimal amount (e.g. "0",
// "0.00", "-0", "-0.00"). Used to decide whether an opening_balance value
// should be omitted from the submitted payload entirely, per the backend's
// own null/zero -> no transaction rule -- checked as a digit pattern,
// never by parsing the string into a Number.
export function isZeroDecimalAmount(normalizedValue: string): boolean {
  return /^-?0+(\.0+)?$/.test(normalizedValue);
}

// Normalizes a decimal money-amount string for submission: trims
// whitespace and converts a comma decimal separator to a point. Callers
// must validate with validateAccountDecimalAmount / validateOpeningBalanceAmount
// before treating the result as safe to send -- this function does not
// itself reject invalid input. Exact mirror of normalizeGoalDecimalAmount.
export function normalizeAccountDecimalAmount(rawValue: string): string {
  return rawValue.trim().replace(",", ".");
}
