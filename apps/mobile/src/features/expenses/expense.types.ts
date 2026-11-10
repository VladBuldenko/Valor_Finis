// Mirrors backend ExpenseResponse
// (services/api/app/modules/expenses/expenses_schemas.py). Every Decimal
// field (amount, base_amount, fx_rate) is a string: the backend serializes
// Decimal as a JSON string, and this app never converts money to a
// JavaScript Number.
//
// account_id is read-only and derived by the backend from the Expense's
// AccountTransaction projection -- Expense has no account_id column. null
// means unlinked. The five FX fields are backend-resolved historical
// snapshot values (null only for an unresolved legacy foreign expense),
// never client-writable.
export type Expense = {
  id: string;
  user_id: string;
  category_id: string | null;
  title: string;
  amount: string;
  currency: string;
  expense_date: string;
  description: string | null;
  source: string;
  account_id: string | null;
  // The create idempotency key the record was created with; null when the
  // create request carried none (and for records created before keys existed).
  client_request_id: string | null;
  base_amount: string | null;
  base_currency: string | null;
  fx_rate: string | null;
  fx_rate_date: string | null;
  fx_source: string | null;
  created_at: string;
  updated_at: string;
};

// Mirrors backend ExpenseCreate (extra="forbid"). id, user_id, and the FX
// snapshot fields are deliberately absent -- the backend rejects them.
// account_id is omitted entirely for an unlinked Expense.
export type ExpenseCreateInput = {
  category_id?: string | null;
  title: string;
  amount: string;
  currency: string;
  expense_date: string;
  description?: string | null;
  source?: string;
  account_id?: string;
  // One UUID per logical create, reused when that same create is retried (see
  // lib/create-attempts.ts). The backend then returns the already-created
  // Expense (200) instead of creating a second one. Optional on the wire: a
  // request without it keeps the legacy, non-idempotent behavior.
  client_request_id?: string;
};

// Mirrors backend ExpenseUpdate. Every field is optional because PATCH
// sends only what changed; an omitted field stays unchanged.
//
// - category_id: null means Uncategorized.
// - description: null clears an existing note.
// - account_id is three-state: omitted leaves the linkage unchanged, a
//   UUID attaches or moves, and null detaches.
export type ExpenseUpdateInput = {
  category_id?: string | null;
  title?: string;
  amount?: string;
  currency?: string;
  expense_date?: string;
  description?: string | null;
  source?: string;
  account_id?: string | null;
};
