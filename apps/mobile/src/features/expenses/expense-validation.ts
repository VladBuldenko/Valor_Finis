export type ExpenseFormValues = {
  title: string;
  amount: string;
  currency: string;
  expenseDate: string;
  description: string;
};

// Matches the expenses table's title VARCHAR(120) / ExpenseBase.title
// max_length.
const MAX_TITLE_LENGTH = 120;

// Matches the expenses table's description VARCHAR(500). The backend
// schema does not enforce this length itself yet, so checking it here
// keeps an oversized note from reaching the database.
const MAX_DESCRIPTION_LENGTH = 500;

// Normalizes a decimal money-amount string for submission: trims
// whitespace and converts a comma decimal separator to a point, matching
// the trim/replace(",", ".") convention used across this app's create/
// edit screens. Callers must validate with validateExpenseForm before
// treating the result as safe to send.
export function normalizeExpenseAmount(rawValue: string): string {
  return rawValue.trim().replace(",", ".");
}

// Validates Expense's always-positive amount: required, digits with up to
// 2 decimal places (the column is NUMERIC(12,2)), no sign/exponent
// notation, and not zero. Stays string-based throughout -- the value is
// never parsed into a JavaScript Number (CLAUDE.md Decimal-only rule).
function validateExpenseAmount(rawValue: string): string | null {
  const normalized = normalizeExpenseAmount(rawValue);

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
 * Validates expense form input shared by the create and edit screens.
 * First-error-wins, returns null when valid. Only input shape is checked
 * here: the backend is the sole authority on calendar-date validity, FX
 * availability, future-dated foreign-currency rejection, and Expense/
 * Account currency matching.
 */
export function validateExpenseForm(
  values: ExpenseFormValues,
): string | null {
  const trimmedTitle = values.title.trim();

  if (!trimmedTitle) {
    return "Title is required.";
  }

  if (trimmedTitle.length > MAX_TITLE_LENGTH) {
    return `Title must be ${MAX_TITLE_LENGTH} characters or fewer.`;
  }

  const amountError = validateExpenseAmount(values.amount);

  if (amountError) {
    return amountError;
  }

  if (!/^[A-Z]{3}$/.test(values.currency.trim().toUpperCase())) {
    return "Currency must be exactly 3 letters.";
  }

  if (!/^\d{4}-\d{2}-\d{2}$/.test(values.expenseDate.trim())) {
    return "Date must use YYYY-MM-DD format.";
  }

  if (values.description.trim().length > MAX_DESCRIPTION_LENGTH) {
    return `Description must be ${MAX_DESCRIPTION_LENGTH} characters or fewer.`;
  }

  return null;
}
