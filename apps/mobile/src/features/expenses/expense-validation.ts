export type ExpenseFormValues = {
  title: string;
  amount: string;
  expenseDate: string;
};

/**
 * Validates expense form input shared by the create and edit screens.
 * Returns an error message for the first invalid field, or null when valid.
 */
export function validateExpenseForm(
  values: ExpenseFormValues,
): string | null {
  if (!values.title.trim()) {
    return "Title is required.";
  }

  const numericAmount = Number(
    values.amount.trim().replace(",", "."),
  );

  if (!Number.isFinite(numericAmount) || numericAmount <= 0) {
    return "Amount must be greater than zero.";
  }

  if (!/^\d{4}-\d{2}-\d{2}$/.test(values.expenseDate)) {
    return "Date must use YYYY-MM-DD format.";
  }

  return null;
}
