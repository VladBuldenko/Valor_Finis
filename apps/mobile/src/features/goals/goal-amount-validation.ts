// Validates a decimal money-amount string against the shared contract used
// by every Goal-related amount field (target_amount, GoalTransaction.amount):
// positive, up to 2 decimal places, no exponent/negative notation, no
// leading/trailing garbage. Deliberately never parses the value as a
// JavaScript Number (see CLAUDE.md's Decimal-only rule, and VF-016F's
// mobile financial-string rule) -- both the regex shape check and the
// zero check below stay string-based throughout.
//
// A comma is normalized to a decimal point first, matching the trim/
// replace(",", ".") convention already used across this app's create/edit
// screens before a value is sent to the backend.
//
// Returns a user-facing error message, or null when the value is valid.
export function validateGoalDecimalAmount(
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

  // A purely-zero value (e.g. "0", "0.0", "0.00") matches the shape check
  // above but must still be rejected -- checked as a digit pattern, never
  // by parsing the string into a Number.
  if (/^0+(\.0+)?$/.test(normalized)) {
    return `${fieldLabel} must be greater than zero.`;
  }

  return null;
}

// Inline feedback for an amount field while the user types (VF-MVP-MOBILE-UX-001).
// An EMPTY field gives no message (the submit button simply stays disabled until
// something is entered); any other input gets exactly the message
// validateGoalDecimalAmount produces, so what is shown here is what a submit
// would have said. Shape only: whether the amount fits a balance or a capacity
// is decided by the backend, never here.
export function validateGoalAmountInput(
  rawValue: string,
  fieldLabel: string,
): string | null {
  return rawValue ? validateGoalDecimalAmount(rawValue, fieldLabel) : null;
}

// Normalizes a decimal money-amount string for submission: trims
// whitespace and converts a comma decimal separator to a point. Callers
// must validate with validateGoalDecimalAmount before treating the result
// as safe to send -- this function does not itself reject invalid input.
export function normalizeGoalDecimalAmount(rawValue: string): string {
  return rawValue.trim().replace(",", ".");
}
