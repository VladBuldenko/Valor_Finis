// Mirrors backend IncomeBase.source's Literal
// (services/api/app/modules/income/income_schemas.py).
export type IncomeSource = "salary" | "freelance" | "refund" | "gift" | "other";

export const INCOME_SOURCES: IncomeSource[] = [
  "salary",
  "freelance",
  "refund",
  "gift",
  "other",
];

// Readable labels for the backend's lowercase source literals --
// presentation-only, shared by the Income list, create, and edit screens.
export const INCOME_SOURCE_LABELS: Record<IncomeSource, string> = {
  salary: "Salary",
  freelance: "Freelance",
  refund: "Refund",
  gift: "Gift",
  other: "Other",
};

// Mirrors backend IncomeResponse exactly. Every Decimal field (amount,
// base_amount, fx_rate) is a string: the backend serializes Decimal as a
// JSON string, and this app never converts money to a JavaScript Number.
//
// account_id is read-only and derived by the backend from the Income's
// AccountTransaction projection -- Income has no account_id column. null
// means unlinked. The five FX fields are backend-resolved historical
// snapshot values, never client-writable.
export type Income = {
  id: string;
  user_id: string;
  amount: string;
  currency: string;
  received_at: string;
  source: IncomeSource;
  description: string | null;
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

// Mirrors backend IncomeCreate (extra="forbid"). id, user_id, and the FX
// snapshot fields are deliberately absent -- the backend rejects them.
// account_id is omitted entirely for an unlinked Income.
export type IncomeCreateInput = {
  amount: string;
  currency: string;
  received_at: string;
  source: IncomeSource;
  description?: string;
  account_id?: string;
  // One UUID per logical create, reused when that same create is retried (see
  // lib/create-attempts.ts). The backend then returns the already-created
  // Income (200) instead of creating a second one. Optional on the wire: a
  // request without it keeps the legacy, non-idempotent behavior.
  client_request_id?: string;
};

// Mirrors backend IncomeUpdate. Every field is optional because PATCH
// sends only what changed; an omitted field stays unchanged.
//
// - description: null clears an existing note.
// - account_id is three-state: omitted leaves the linkage unchanged, a
//   UUID attaches or moves, and null detaches.
export type IncomeUpdateInput = {
  amount?: string;
  currency?: string;
  received_at?: string;
  source?: IncomeSource;
  description?: string | null;
  account_id?: string | null;
};
