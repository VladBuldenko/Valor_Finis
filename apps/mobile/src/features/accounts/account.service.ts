import { apiRequest } from "../../api/api-client";

import type {
  Account,
  AccountCreateInput,
  AccountTransaction,
  AccountTransactionCreateInput,
  AccountUpdateInput,
} from "./account.types";

/**
 * Returns all financial accounts that belong to the authenticated user.
 *
 * There is no GET /accounts/{id} endpoint -- Account detail/edit screens
 * resolve a single account from this same list response instead (see
 * account-detail-screen.tsx / account-edit-screen.tsx), matching the
 * established Goals pattern.
 */
export async function getAccounts(): Promise<Account[]> {
  return apiRequest<Account[]>("/api/v1/accounts");
}

/**
 * Creates an account for the authenticated user, optionally with a signed
 * opening balance that the backend converts into a single opening_balance
 * ledger transaction (positive -> credit, negative -> debit, omitted/zero
 * -> no transaction at all).
 */
export async function createAccount(
  accountData: AccountCreateInput,
): Promise<Account> {
  return apiRequest<Account>("/api/v1/accounts", {
    method: "POST",
    body: JSON.stringify(accountData),
  });
}

/**
 * Updates an account owned by the authenticated user.
 * Only the fields present in accountData are changed -- callers are
 * responsible for omitting fields that did not change (see
 * AccountUpdateInput / the backend's exclude_unset PATCH semantics).
 */
export async function updateAccount(
  accountId: string,
  accountData: AccountUpdateInput,
): Promise<Account> {
  return apiRequest<Account>(`/api/v1/accounts/${accountId}`, {
    method: "PATCH",
    body: JSON.stringify(accountData),
  });
}

/**
 * Deletes an account owned by the authenticated user.
 * The backend returns 204 No Content on success, which apiRequest already
 * handles centrally (it returns undefined without parsing a body). The
 * backend rejects this with 409 when the account has any transaction
 * history -- this function never pre-checks that client-side.
 */
export async function deleteAccount(accountId: string): Promise<void> {
  return apiRequest<void>(`/api/v1/accounts/${accountId}`, {
    method: "DELETE",
  });
}

/**
 * Returns an account's full transaction history, newest first (the
 * backend's own ordering -- never re-sorted client-side). Includes
 * opening_balance, adjustment, and any synchronized income/expense
 * projection rows.
 */
export async function getAccountTransactions(
  accountId: string,
): Promise<AccountTransaction[]> {
  return apiRequest<AccountTransaction[]>(
    `/api/v1/accounts/${accountId}/transactions`,
  );
}

/**
 * Creates a manual adjustment transaction for an account owned by the
 * authenticated user. There is no client-submitted kind -- the backend
 * always creates kind="adjustment" for every row this endpoint produces.
 * The backend is the sole authority on archived-account rejection (409)
 * -- this never pre-checks that client-side.
 */
export async function createAccountTransaction(
  accountId: string,
  transactionData: AccountTransactionCreateInput,
): Promise<AccountTransaction> {
  return apiRequest<AccountTransaction>(
    `/api/v1/accounts/${accountId}/transactions`,
    {
      method: "POST",
      body: JSON.stringify(transactionData),
    },
  );
}
