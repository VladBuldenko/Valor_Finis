import type { Expense } from "../expenses/expense.types";

export type ReceiptStatus =
  | "uploaded"
  | "processing"
  | "processed"
  | "confirmed"
  | "failed";

export type Receipt = {
  id: string;
  user_id: string;
  expense_id: string | null;
  file_url: string | null;
  storage_path: string | null;
  status: ReceiptStatus;
  ocr_text: string | null;
  merchant_detected: string | null;
  total_amount_detected: string | null;
  currency_detected: string | null;
  purchase_date_detected: string | null;
  created_at: string;
  updated_at: string;
};

/**
 * Local representation of a picked receipt image, independent from the
 * `expo-image-picker` asset shape so the service layer does not depend on
 * a specific picker library type. The name and MIME type sent to the
 * backend are derived from the file at this URI (see `receipt.service.ts`),
 * not trusted from the picker's self-reported metadata.
 */
export type PickedReceiptImage = {
  uri: string;
};

/**
 * Optional corrections sent on confirmation. Matches the backend
 * `ReceiptConfirmRequest` contract -- every field is optional because a
 * value can come either from OCR-detected data or from this correction.
 */
export type ReceiptConfirmInput = {
  category_id?: string | null;
  title?: string;
  amount?: string;
  currency?: string;
  expense_date?: string;
  description?: string | null;
};

export type ReceiptConfirmResult = {
  receipt: Receipt;
  expense: Expense;
};
