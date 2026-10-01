// Mirrors backend AccountTransferResponse.status
// (services/api/app/modules/accounts/account_transfer_schemas.py). The only
// transition is planned -> posted, performed by the backend's
// POST /account-transfers/{id}/post -- never inferred or applied on the
// client.
export type AccountTransferStatus = "planned" | "posted";

// Mirrors backend AccountTransferResponse exactly (VF-018C/D). amount stays
// the backend's exact decimal string -- never parsed for display or
// arithmetic. currency is server-derived from the two Accounts.
//
// Dates: planned_date is set only for a transfer created as planned and
// keeps its original value after posting; effective_date (the accounting
// date of both ledger rows) and posted_at are set once posted. There is no
// transfer_date here -- that field exists only on the create request.
// status, not the presence of any date, is the authority on the lifecycle.
export type AccountTransfer = {
  id: string;
  user_id: string;
  client_request_id: string;
  source_account_id: string;
  destination_account_id: string;
  amount: string;
  currency: string;
  status: AccountTransferStatus;
  planned_date: string | null;
  effective_date: string | null;
  description: string | null;
  posted_at: string | null;
  created_at: string;
  updated_at: string;
};

// Mirrors backend AccountTransferCreate (extra="forbid"). The server
// classifies transfer_date against its own date: today or earlier creates
// an immediately posted transfer, a later date a planned one. user_id,
// currency, status, planned_date, effective_date, and posted_at are
// server-owned and never sent. client_request_id is the create idempotency
// key -- see transfer-create-attempts.ts for how it is generated and
// reused across retries.
export type AccountTransferCreateInput = {
  client_request_id: string;
  source_account_id: string;
  destination_account_id: string;
  amount: string;
  transfer_date: string;
  description?: string | null;
};

// Body of POST /account-transfers/{id}/post. The backend accepts an omitted
// body (server date), but the mobile client always sends an explicit
// effective_date -- the user's local calendar date -- so a server/local
// date mismatch (the known D13 timezone gap) surfaces as a visible 422
// instead of a silently shifted accounting date.
export type AccountTransferPostInput = {
  effective_date: string;
};
