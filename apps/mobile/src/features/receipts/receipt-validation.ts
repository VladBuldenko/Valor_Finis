export type ReceiptConfirmFormValues = {
  title: string;
  amount: string;
  currency: string;
  expenseDate: string;
};

/**
 * Validates the receipt confirmation form before it is submitted.
 * Mirrors the client-side rules used for manual expense entry
 * (see `expense-validation.ts`), extended with a currency check since
 * OCR can detect or fail to detect a non-default currency.
 * Returns an error message for the first invalid field, or null when valid.
 */
export function validateReceiptConfirmForm(
  values: ReceiptConfirmFormValues,
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

  if (values.currency.trim().length !== 3) {
    return "Currency must be a 3-letter code.";
  }

  return null;
}
