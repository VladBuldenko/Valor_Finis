// Cache handling around receipt confirmation (VF-MVP-CORE-005).
//
// A confirmation is one atomic backend transaction: it either created the Expense (and the optional
// Account debit) and marked the receipt confirmed, or it changed nothing. The client cannot always
// tell which happened: a lost response, a timeout, or a 409 "already confirmed" from another device
// all arrive as a failure even though the Expense may exist. The write is never resent (the transport
// does not retry POST); instead the receipt is reread. If it reads "confirmed", the Expense exists and
// every cache the confirmation touched is refreshed, exactly as after a normal success. Pure and
// framework-free so it can be tested with the Node test runner.
import type { QueryClient } from "@tanstack/react-query";

import { invalidateExpenseQueries } from "../expenses/expense-cache.ts";
import type { Receipt } from "./receipt.types.ts";

export type ReceiptFetcher = (receiptId: string) => Promise<Receipt>;

export type ConfirmRecovery =
  | { confirmed: true; expenseId: string | null }
  | { confirmed: false; expenseId: null };

export const receiptDetailKey = (receiptId: string) => ["receipts", "detail", receiptId] as const;

/**
 * Refreshes the receipt lists and the full Expense/analytics set. `touchedAccount` is true when the
 * created Expense is linked to an Account (its balance and history changed).
 */
export function invalidateConfirmedReceiptQueries(
  queryClient: QueryClient,
  userId: string | undefined,
  touchedAccount: boolean,
): Promise<unknown> {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: ["receipts"] }),
    invalidateExpenseQueries(queryClient, userId, touchedAccount),
  ]);
}

/**
 * Called after a confirmation request FAILED. Rereads the receipt and returns whether the server
 * actually committed it. The Account caches are refreshed conservatively (the link is unknown here)
 * only when it did. Never throws: when the reread itself fails the failure message the user already
 * has stays the truth and the detail query is left to refetch.
 */
export async function recoverFailedConfirmation(
  queryClient: QueryClient,
  userId: string | undefined,
  receiptId: string,
  fetchReceipt: ReceiptFetcher,
): Promise<ConfirmRecovery> {
  let receipt: Receipt;

  try {
    receipt = await fetchReceipt(receiptId);
  } catch {
    await queryClient.invalidateQueries({ queryKey: receiptDetailKey(receiptId) });

    return { confirmed: false, expenseId: null };
  }

  queryClient.setQueryData(receiptDetailKey(receiptId), receipt);

  if (receipt.status !== "confirmed") {
    return { confirmed: false, expenseId: null };
  }

  await invalidateConfirmedReceiptQueries(queryClient, userId, true);

  return { confirmed: true, expenseId: receipt.expense_id };
}
