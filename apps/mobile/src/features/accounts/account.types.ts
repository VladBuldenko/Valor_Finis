export type AccountType = "checking" | "savings" | "cash";
export type AccountStatus = "active" | "archived";

// Mirrors backend AccountResponse (services/api/app/modules/accounts/account_schemas.py),
// which itself extends AccountBase. current_balance is always ledger-derived
// by the backend from account_transactions -- it is never computed or
// summed on the client, and money fields arrive as JSON strings, matching
// every other financial contract in this app (see Goal in
// ../goals/goal.types.ts) -- never parse them for display or arithmetic,
// only render the exact string the backend returns.
export type Account = {
  id: string;
  user_id: string;
  name: string;
  type: AccountType;
  currency: string;
  status: AccountStatus;
  current_balance: string;
  created_at: string;
  updated_at: string;
};

// Mirrors backend AccountCreate. status is intentionally omitted entirely:
// a new Account is always implicitly "active", and this form has no reason
// to expose it (mirrors how Goal's create form omits status/current_amount).
// opening_balance is a SIGNED decimal string -- positive creates a credit
// opening_balance ledger transaction, negative creates a debit one, and
// null/zero creates no transaction at all (it is never persisted as an
// Account field either way). opening_balance_date is ignored by the backend
// whenever opening_balance is omitted or zero, so this form only sends it
// alongside a real non-zero opening_balance.
export type AccountCreateInput = {
  name: string;
  type: AccountType;
  currency?: string;
  opening_balance?: string;
  opening_balance_date?: string;
};

// Mirrors backend AccountUpdate. Every field is optional -- an omitted
// field is left unchanged by the backend (exclude_unset PATCH semantics).
// The backend rejects an explicit null for any of these four fields, so
// they stay plain optional values, never nullable. status IS part of the
// backend contract here, but this input type is used only by the Edit
// Account form, which never touches status -- Archive/Reactivate on
// Account detail sends { status } directly as its own narrow PATCH
// (see account-detail-screen.tsx), matching the task's explicit split
// between metadata editing and the lifecycle action.
export type AccountUpdateInput = {
  name?: string;
  type?: AccountType;
  currency?: string;
  status?: AccountStatus;
};

// Mirrors backend AccountTransactionResponse's `kind` field
// (services/api/app/modules/accounts/account_transaction_schemas.py).
// opening_balance is created only via Account creation; income/expense are
// synchronized projections from other modules (VF-017D/E) -- a client can
// never create any of these three directly (see
// AccountTransactionCreateInput below, which has no kind field at all).
export type AccountTransactionKind =
  | "opening_balance"
  | "adjustment"
  | "income"
  | "expense";

// Mirrors backend AccountTransactionResponse. amount is always positive;
// direction (not kind) carries the sign -- unlike GoalTransaction, which
// has no separate direction column and infers sign from `type`, every
// AccountTransaction row states its own sign explicitly via `direction`.
// income_id/expense_id are mutually exclusive and both null for direct
// (opening_balance/adjustment) rows. There is no updated_at -- transaction
// rows are immutable/append-only, and there is no PATCH/DELETE endpoint
// for them at all. Money fields stay JSON strings -- never parse them for
// display or arithmetic, only render the exact string the backend returns.
export type AccountTransaction = {
  id: string;
  account_id: string;
  user_id: string;
  kind: AccountTransactionKind;
  direction: "credit" | "debit";
  amount: string;
  transaction_date: string;
  description: string | null;
  income_id: string | null;
  expense_id: string | null;
  created_at: string;
};

// Mirrors backend AccountTransactionCreate. There is deliberately no `kind`
// field -- the backend always creates kind="adjustment" for every row this
// endpoint produces, and rejects a client-sent kind outright (422).
// user_id/account_id are intentionally omitted -- user_id comes from
// authentication and account_id comes from the request path, not the body.
export type AccountTransactionCreateInput = {
  direction: "credit" | "debit";
  amount: string;
  transaction_date: string;
  description?: string | null;
};
