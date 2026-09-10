export type BudgetFormValues = {
  name: string;
  limitAmount: string;
  startDate: string;
  endDate: string;
};

/**
 * Validates budget create form input.
 * Mirrors the client-side rules used for manual expense entry
 * (see expense-validation.ts), extended with an end-date-after-start-date
 * check matching the backend's own date range validation.
 * Returns an error message for the first invalid field, or null when valid.
 */
export function validateBudgetForm(
  values: BudgetFormValues,
): string | null {
  if (!values.name.trim()) {
    return "Name is required.";
  }

  const numericLimitAmount = Number(
    values.limitAmount.trim().replace(",", "."),
  );

  if (!Number.isFinite(numericLimitAmount) || numericLimitAmount <= 0) {
    return "Limit amount must be greater than zero.";
  }

  if (!/^\d{4}-\d{2}-\d{2}$/.test(values.startDate)) {
    return "Start date must use YYYY-MM-DD format.";
  }

  const trimmedEndDate = values.endDate.trim();

  if (trimmedEndDate) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(trimmedEndDate)) {
      return "End date must use YYYY-MM-DD format.";
    }

    if (trimmedEndDate < values.startDate) {
      return "End date must be on or after the start date.";
    }
  }

  return null;
}
