import { validateExpenseForm } from "../expenses/expense-validation";

export type ReceiptConfirmFormValues = {
  title: string;
  amount: string;
  currency: string;
  expenseDate: string;
  description: string;
};

/**
 * Validates the receipt confirmation form before it is submitted.
 * Confirming a receipt creates an Expense, so the input rules are exactly
 * the manual Expense rules and are delegated to validateExpenseForm
 * (string-only amount check, title <= 120, 3-letter currency, YYYY-MM-DD
 * date shape, description <= 500). Kept as the Receipt entry point so the
 * review screen does not depend on how those rules are composed.
 * Returns an error message for the first invalid field, or null when valid.
 */
export function validateReceiptConfirmForm(
  values: ReceiptConfirmFormValues,
): string | null {
  return validateExpenseForm(values);
}
