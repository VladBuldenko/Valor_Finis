# Account Transfers — Approved Contract (VF-018A)

Status: **approved contract, not implemented.**
Base: `main` at `6adb3d6` (after PR #60, VF-DOC-01).
Decision record: D1–D19 (see section 31).

This document is the single source of truth for the VF-018 Account Transfers
block. VF-018B–VF-018E must be implementable from it without repeating
product discovery. Nothing described here exists in code yet: every endpoint,
table, column, error, and test below is future work unless a later slice says
otherwise. `docs/api-contract.md`, `docs/database-schema.md`,
`docs/architecture.md`, `docs/roadmap.md`, and `README.md` are updated by the
implementation slices, not by VF-018A.

---

## 1. Purpose

A user must be able to record an internal movement of their own money from
one Account to another, either:

- as something that **already happened** (posted immediately), or
- as something **expected to happen in the future** (planned), which is later
  confirmed manually (posted).

Example:

```text
Before:  Checking 1000.00 EUR   Savings    0.00 EUR
Transfer 300.00 EUR  Checking -> Savings  (posted)
After:   Checking  700.00 EUR   Savings  300.00 EUR
```

Planned transfers exist to support financial planning (planned outgoing,
planned incoming, projected balance) without distorting the current balance.

---

## 2. Domain definition

An **AccountTransfer** is a canonical record of money moving between two
Accounts owned by the same user, in the same currency.

- It moves existing money; it neither creates nor destroys it.
- The sum of all of a user's Account balances in one currency is unchanged by
  a posted transfer.
- It has a lifecycle: `planned` (expected, no ledger effect) or `posted`
  (happened, reflected in the Account ledger).

---

## 3. Why Transfer is not Income, Expense, or Adjustment

| Alternative | Why it is wrong for transfers |
|---|---|
| Income + Expense pair | A transfer is not an external flow. Modelling it as Income + Expense would inflate both totals and corrupt monthly summary, category summary, budget status, spending trend, category trends, and forecast. Categories, budgets, and FX snapshots are meaningless for it. |
| Two manual `adjustment` rows | Adjustments are direct, immutable, unlinked rows with no canonical owner. They cannot be deleted, have no counterpart link, and read as unexplained reconciliation corrections in history. There is no way to represent "planned". |
| Two ledger rows with a shared group id, no canonical table | Date/description would be duplicated across rows, there is no ownership FK target, no single record for list/post/delete, and nowhere to hold planned state. |
| Balance = UNION(ledger, transfers) | Breaks the invariant that `account_transactions` alone is the authoritative Account balance source. |

A Transfer is therefore its own canonical entity with ledger projections,
following the existing Income/Expense "canonical record + synchronized
projection" pattern (VF-017D/VF-017E).

---

## 4. Canonical AccountTransfer entity (D1, D17)

Conceptual fields:

| Field | Type | Meaning |
|---|---|---|
| `id` | UUID | Primary key. |
| `user_id` | UUID | Owner, from authenticated identity only. |
| `client_request_id` | UUID | Client-generated create idempotency key (section 10). |
| `source_account_id` | UUID | Account money leaves. |
| `destination_account_id` | UUID | Account money enters. |
| `amount` | NUMERIC(12,2) | Always positive. |
| `currency` | VARCHAR(3) | Server-derived from the Accounts, never client input. |
| `status` | `planned` \| `posted` | Lifecycle state (section 5). |
| `planned_date` | DATE, nullable | Original expected date. Set only when created as planned. |
| `effective_date` | DATE, nullable | Accounting date the money actually moved. Set when posted. |
| `description` | VARCHAR(500), nullable | Optional note. Single canonical copy of the text. |
| `posted_at` | TIMESTAMPTZ, nullable | Technical moment Valor Finis changed status to posted. |
| `created_at` | TIMESTAMPTZ | Record creation time. |
| `updated_at` | TIMESTAMPTZ | Last modification (changes on posting). |

There is **no `transfer_date` persistence column**. `transfer_date` exists only
as a create-request field (section 7).

The Account row never gains a balance column; balances stay ledger-derived.

---

## 5. Planned / posted lifecycle (D7, D11)

```text
            create (transfer_date <= today)
  ───────────────────────────────────────────►  POSTED ── delete ──► gone (+ both ledger rows)
            create (transfer_date > today)            ▲
  ──────────►  PLANNED  ── POST /{id}/post ───────────┘
                  │
                  └── delete ──► gone (ledger untouched)
```

| | planned | posted |
|---|---|---|
| Canonical Transfer row | exists | exists |
| AccountTransaction rows | **zero** | **exactly two** (source debit, destination credit) |
| Current Account balances | unchanged | reflect the transfer |
| `GET /account-transfers` | visible | visible |
| Account transaction history | **not visible** | visible (both sides) |
| `planned_date` | non-null | non-null if it began as planned, otherwise null |
| `effective_date` | null | non-null |
| `posted_at` | null | non-null |

Rules:

- Status is always decided by the server. The client never sends `status`.
- The only transition is `planned -> posted`. There is no unpost.
- There is no PATCH in the MVP. A correction is delete + create.
- An **overdue** planned transfer (`planned_date <= today`, not yet posted)
  stays `planned` until the user posts it manually. There is no automatic
  scheduler.

---

## 6. Date model (D13, D17)

| Field | Meaning | Written by | Mutability |
|---|---|---|---|
| `planned_date` | When the transfer was expected to happen | Server, from create `transfer_date` when it is in the future | Never changes, including after posting |
| `effective_date` | Accounting date on which the money is considered actually moved; the `transaction_date` of both ledger rows | Server: from create `transfer_date` (immediate post) or from the post request / today (manual post) | Never changes (no PATCH) |
| `posted_at` | Technical timestamp of the status change to posted | Server, `now()` | Never changes |

Example: planned for `2026-10-15`, user confirms the money moved on
`2026-10-18` → `planned_date = 2026-10-15`, `effective_date = 2026-10-18`,
both ledger rows dated `2026-10-18`, `posted_at` = the moment of confirmation.
The planned date is never silently reused as the accounting date.

Naming rationale: `planned_date` matches the `planned` status vocabulary
(`scheduled_for` would imply an automatic scheduler that does not exist);
`effective_date` is the standard accounting "value date" term and avoids
confusion with the technical `posted_at`.

### Definition of "today" (D13)

- `today` is the **server date**, the same notion the existing FX
  future-dated rule already uses (`as_of=date.today()`).
- It is resolved once per service call through an `as_of` parameter that
  defaults to the server date (existing FX pattern), so boundary behavior is
  testable deterministically.
- Known gap: the production process on Render is expected to run in UTC (to
  be observed at deployment). For users east of UTC, during the first hours
  after local midnight the local "today" is the server's "tomorrow". In that
  window a local-today create is classified `planned`, and a local-today
  `effective_date` is rejected as future. This is documented, not solved, in
  VF-018 (see section 29).

---

## 7. Create semantics (D2, D3, D7, D14, D18)

`POST /api/v1/account-transfers`

The client sends exactly one date, `transfer_date`. The server classifies it:

| Condition | status | planned_date | effective_date | posted_at | Ledger rows |
|---|---|---|---|---|---|
| `transfer_date <= today` | `posted` | NULL | `transfer_date` | `now()` | both created |
| `transfer_date > today` | `planned` | `transfer_date` | NULL | NULL | none |

There is no lower bound on `transfer_date`; a past date creates a backdated
posted transfer, consistent with adjustments.

Service flow:

1. Validate the request schema (section 23).
2. **Idempotency fast path**: look up an existing transfer by
   `(user_id, client_request_id)` without locks. If found, compare and return
   replay (200) or conflict (409). No account business validation runs on
   this path (section 10).
3. Lock both Accounts `FOR UPDATE`, scoped by `user_id`, in ascending UUID
   order. This happens for **both** planned and posted creates (reason in
   section 11.4). A missing or foreign Account → 404.
4. Validate: both Accounts `active` (else 409), same currency (else 422).
5. Insert the canonical transfer (flush) with `currency` = the Accounts'
   currency and the status/date fields from the table above.
6. If posted: create both ledger projections with one repository primitive
   (section 15).
7. Commit once.
8. If step 5 fails on the `(user_id, client_request_id)` unique constraint
   (concurrent duplicate), roll back, reload the existing transfer, compare,
   and return 200 or 409 (section 10).

Response: `201 Created` with `AccountTransferResponse`.

---

## 8. Manual posting semantics (D3, D12)

`POST /api/v1/account-transfers/{id}/post`

Optional body:

```json
{ "effective_date": "2026-10-18" }
```

- If the body or `effective_date` is omitted, `effective_date = today`.
- `effective_date` must not be in the future → otherwise 422.
- `effective_date` may be **before or after** `planned_date` (early or late
  real-world execution). There is no "not yet due" restriction: the rule
  `effective_date <= today` alone guarantees the ledger never receives a
  future-dated transfer row.
- Mobile always sends `effective_date` explicitly (default shown as today in
  the confirmation UI) so that timezone-window problems surface as a visible
  422 rather than a silently shifted date.

Service flow:

1. Resolve `effective_date` (default `as_of`), reject a future date → 422.
2. Lock the transfer `FOR UPDATE`, scoped by `user_id`. Missing or foreign →
   404.
3. `status != 'planned'` → 409 `AccountTransferAlreadyPostedError`.
4. Lock both Accounts `FOR UPDATE` in ascending UUID order, re-verifying
   ownership.
5. Either Account archived → 409 `AccountArchivedError`. The transfer stays
   `planned`; nothing is written.
6. Re-verify currency match → 422. This is defense in depth: section 11 and
   the composite FKs already make a mismatch impossible.
7. Set `status='posted'`, `effective_date`, `posted_at=now()` (flush).
8. Create both ledger projections with `transaction_date = effective_date`.
9. Commit once. Any failure rolls back; the transfer stays `planned` with zero
   ledger rows.

`planned_date` is never modified by posting.

Response: `200 OK` with `AccountTransferResponse` (status `posted`).

Posting needs no idempotency key: the state machine allows the transition at
most once. A retry after a lost response returns 409
`AccountTransferAlreadyPostedError`; the client refetches and sees `posted`.

---

## 9. Delete semantics (D3, D6)

`DELETE /api/v1/account-transfers/{id}` → `204 No Content`

One uniform path for both statuses:

1. Lock the transfer `FOR UPDATE`, scoped by `user_id`. Missing or foreign →
   404.
2. Lock both Accounts `FOR UPDATE` in ascending UUID order.
3. Delete the canonical transfer.
4. Commit once.

| Status | Effect |
|---|---|
| planned | Only the canonical row is removed. No ledger effect. |
| posted | The canonical row is removed; both ledger rows are removed by `ON DELETE CASCADE` inside the same transaction. Balances return to their pre-transfer values. |

- Hard delete. No reversal entity, no tombstone, no audit trail — the same as
  Income/Expense deletion.
- An archived Account on either side does **not** block deletion in either
  status (removing history is a correction, not new activity; Income/Expense
  precedent).
- The uniform path locks Accounts even for planned deletes so that a
  concurrent post (which may change the status while the delete waits for the
  transfer lock) is always handled with the Account locks already held.
- Deleting a transfer frees its `client_request_id` (section 10.6).
- If an Account has no remaining ledger history and no planned references
  after the delete, it becomes deletable and its currency becomes changeable
  again (existing rules).
- A retried DELETE after a lost response returns 404; the client treats 404
  on delete as success.

---

## 10. Idempotency (D9, D18)

### 10.1 Design

| Question | Decision | Rationale |
|---|---|---|
| Body field vs `Idempotency-Key` header | **Body field `client_request_id`** | Stored on the canonical row, validated by Pydantic, visible in the response, protected by one UNIQUE constraint. A header usually implies a generic key store/response cache, which is explicitly not wanted. |
| Required vs optional | **Required** | New endpoint, single client, nothing to stay compatible with. An optional key would leave the duplicate hole open. |
| Exposed in response | **Yes** | Lets the client reconcile after a retry. It is client-generated and user-scoped, so nothing leaks. |
| Scope | `(user_id, client_request_id)` | The same UUID from two different users never collides; lookups are always user-scoped. |

Client-side submit disabling remains as UX only; it is not the protection.

### 10.2 First create

Normal create flow (section 7) → `201 Created`.

### 10.3 Identical retry

Same `client_request_id` and the same original create payload:

- `200 OK` with the **current** state of the existing transfer (for example
  `status=posted` if it was posted since).
- No new canonical row, no new ledger rows, no balance change.
- No response cache: the current representation is returned.
- **Account business validation is not rerun.** The operation already
  happened. If an Account was archived after the original create, the
  identical replay still returns the existing transfer, not 409.
- No reclassification: a retry that arrives after midnight still returns the
  record classified at original create time.

"Same payload" compares against stored fields:

| Request field | Compared with |
|---|---|
| `source_account_id` | `source_account_id` |
| `destination_account_id` | `destination_account_id` |
| `amount` | `amount`, as Decimal equality (`"300"` equals `"300.00"`) |
| `transfer_date` | `COALESCE(planned_date, effective_date)` |
| `description` | `description`, after schema normalization |

`COALESCE(planned_date, effective_date)` always reconstructs the original
request date because `planned_date` is immutable and an immediately posted
transfer's `effective_date` is immutable. **This relies on "no PATCH".** If
PATCH is ever introduced, the comparison must be revisited.

### 10.4 Conflicting retry

Same `client_request_id`, different payload:

- `409 Conflict` — `AccountTransferIdempotencyConflictError`.
- The existing transfer is not revealed and nothing is written.
- 409 (not 422) because the same body with a fresh UUID would be valid; the
  conflict is with existing server state.

### 10.5 Concurrent duplicate create

Two requests with the same key can both miss the fast-path lookup. The
second INSERT then fails on `uq_account_transfers_user_id_client_request_id`.

- The repository catches `IntegrityError`, reads
  `error.orig.diag.constraint_name` (existing pattern in
  `budget_repository.py`), and raises an internal signal.
- The service rolls back (releasing Account locks), reloads the existing
  transfer by `(user_id, client_request_id)`, compares, and returns 200 or
  409.
- Never a 500.

### 10.6 After deletion — accepted residual MVP risk

The key lives on the hard-deleted canonical row, so **after a hard DELETE the
same `client_request_id` can be reused and will create a new transfer.**

This is accepted deliberately:

- To delete a transfer the user must have seen it, which means the original
  create was confirmed and retries of that form have already stopped.
- Resurrection requires the user to press retry on a stale form after the
  delete.
- Preventing it needs a persistent key/tombstone table or soft delete, which
  contradicts the approved hard-delete model.

Client mitigation (D19): a key lives for one create confirmation flow, is
reused for retries of that flow, and is regenerated after success or when the
form is closed. Stronger persistent idempotency is a known follow-up
(section 29).

---

## 11. Account lifecycle interaction (D3, D14)

### 11.1 Archive

| Operation | Rule |
|---|---|
| Create (planned or posted) from or to an archived Account | 409 `AccountArchivedError` |
| Archive an Account that has planned transfers | **Allowed**. The planned transfers stay `planned`. |
| Post a planned transfer when either Account is archived | 409 `AccountArchivedError`. The transfer stays `planned` with zero ledger rows. |
| Post after the Account is reactivated | Allowed. |
| Read historical transfers after archive | Allowed. |
| Delete a planned or posted transfer involving an archived Account | Allowed. |

A transfer is never silently posted into or out of an archived Account.

### 11.2 Currency change

An Account referenced by any **planned** transfer (as source or destination)
cannot change currency → 409 `AccountReferencedByPlannedTransferError`.

The planned amount is expressed in that currency; changing it would make the
plan meaningless. The composite currency FK (section 20) already blocks the
change at the database level; without the service check `update_account`
would fail with a raw `IntegrityError` (500).

### 11.3 Account deletion

An Account referenced by any **planned** transfer cannot be deleted → 409
`AccountReferencedByPlannedTransferError`. Cascading deletion of plans was
rejected because it would silently destroy planning data. Without the service
check, FK RESTRICT would surface as a 500 (planned transfers have no ledger
rows, so the existing `has_transactions_for_account` check does not see
them).

Check order inside `update_account` / `delete_account`, under the existing
Account `FOR UPDATE` lock:

1. existing ledger-history check → existing errors
   (`AccountCurrencyImmutableError` / `AccountDeletionNotAllowedError`);
2. then the planned-reference check → `AccountReferencedByPlannedTransferError`.

A posted transfer always implies ledger rows, so it is caught by step 1.

### 11.4 Why create locks Accounts even for planned transfers

Without Account locks, creating a plan concurrently with a currency change or
deletion of a fresh Account would let the FK check wait for the other
transaction and then fail with `IntegrityError` (500). Taking the Account
locks first serializes the operations, so every outcome is clean: 409, 404, or
422.

### 11.5 Module placement (D10)

Because `account_service` must read `account_transfers`, a separate module
would create a bidirectional module dependency. Transfers therefore live
inside `services/api/app/modules/accounts/`:

```text
account_transfer_models.py
account_transfer_schemas.py
account_transfer_errors.py
account_transfer_repository.py
account_transfer_service.py
account_transfer_router.py      # router prefix: /account-transfers (mounted under /api/v1)
```

Transfer projection primitives live in the existing
`account_transaction_repository.py`, next to the Income/Expense primitives.
The model is registered in `app/db/database_models.py`.

---

## 12. Currency rules (D2)

- MVP is **same-currency only**: EUR → EUR allowed, EUR → USD rejected
  (422 `AccountTransferCurrencyMismatchError`).
- `currency` is server-derived from the Accounts and stored on the transfer.
  The client cannot send it (`extra="forbid"` → 422).
- Checked at create and re-checked at post.
- Database direction: composite FKs
  `(source_account_id, user_id, currency)` and
  `(destination_account_id, user_id, currency)` →
  `accounts(id, user_id, currency)`. Both reference the same
  `transfer.currency` column, so source, destination, and transfer currencies
  cannot diverge, and a referenced Account's currency cannot change at the
  database level.
- No FX conversion for transfers. No FX provider call is ever made by
  transfer code.

---

## 13. Negative balance rule (D4)

- A transfer (create or post) is allowed even when the source balance is
  insufficient; the resulting balance may be negative.
- There is no insufficient-funds validation anywhere in this feature.
- Rationale: Valor Finis Accounts describe financial state; they are not
  payment-authorization accounts. This matches the existing Account model
  (`account_models.py`, `account_service.create_account_transaction`).

---

## 14. Ownership

- `user_id` always comes from `CurrentUser`, never from request payloads.
- Every Account and transfer lookup/lock is scoped by `user_id`.
- Another user's Account or transfer behaves as not found (404) and never
  leaks existence.
- `source_account_id != destination_account_id` (schema 422 + DB CHECK).
- Cross-user transfers are out of scope.
- Database defense in depth: composite FKs to `accounts(id, user_id, …)` and
  `(transfer_id, user_id) -> account_transfers(id, user_id)` make a cross-user
  transfer or projection impossible even through direct SQL.

---

## 15. AccountTransaction projections

A posted transfer has exactly two rows in `account_transactions`:

| Side | account_id | kind | direction | amount | transaction_date | transfer_id | description |
|---|---|---|---|---|---|---|---|
| Source | `source_account_id` | `transfer` | `debit` | `transfer.amount` | `effective_date` | `transfer.id` | NULL |
| Destination | `destination_account_id` | `transfer` | `credit` | `transfer.amount` | `effective_date` | `transfer.id` | NULL |

- The side is identified by `direction`; one `transfer_id` column is
  sufficient.
- `description` stays NULL on projection rows; the transfer's own description
  is the single canonical copy (same rule as Income/Expense projections).
- Rows are created only by one primitive, `create_transfer_projections`, which
  hardcodes `kind`, both directions, and `description=None`, creates **both**
  rows in one call, and refuses (plain `ValueError`, existing
  `_validate_*_for_mutation` pattern) unless `transfer.status == 'posted'`.
- It is called from exactly two service paths: posted create and manual post.
- There is no update primitive and no delete primitive for transfer rows.
  They disappear only through `ON DELETE CASCADE` when the canonical transfer
  is deleted.
- There is no direct PATCH/DELETE endpoint for any AccountTransaction row
  (unchanged).
- Transfer rows count as ledger history for the existing currency-immutability
  and Account-deletion rules.

---

## 16. Account history read model (D8)

`GET /api/v1/accounts/{account_id}/transactions` — changes to
`AccountTransactionResponse`:

- `kind` Literal gains `"transfer"`.
- New `transfer_id: Optional[UUID]` — set only on transfer rows.
- New `counterparty_account_id: Optional[UUID]` — set only on transfer rows:
  `destination_account_id` for the debit row, `source_account_id` for the
  credit row.

Rules:

- Only posted transfers appear, because only they have ledger rows. Planned
  transfers never appear in Account history.
- The counterparty is resolved without N+1: one bulk user-scoped mapping query
  (same shape as `get_income_account_links_for_user`), applied by an explicit
  response builder.
- The counterparty name is not duplicated into the response; mobile resolves
  it from the cached `GET /accounts` list, which includes archived Accounts.
- Existing ordering is unchanged: `transaction_date DESC, created_at DESC,
  id DESC`.

Compatibility constraint: the `kind` Literal widening must ship **no later
than** the first slice in which a `kind='transfer'` row can exist in the
database. Otherwise history responses for affected Accounts would fail
response validation (500).

Older mobile builds receiving a `transfer` row render an empty kind label but
the correct sign and amount (sign comes from `direction`). Transfer rows can
only exist once the new endpoints are used, so the risk is low.

---

## 17. Current vs projected balance semantics (D15, D16)

```text
current_balance(A)   = Σ credit − Σ debit over account_transactions(A)    -- unchanged
planned_incoming(A)  = Σ amount of planned transfers where destination = A
planned_outgoing(A)  = Σ amount of planned transfers where source = A
projected_balance(A) = current_balance(A) + planned_incoming(A) − planned_outgoing(A)
```

- `AccountResponse.current_balance` is unchanged: ledger only. Planned
  transfers never affect it.
- Projected arithmetic is currency-safe because every participant shares one
  currency (D2).
- The definition includes **all** planned transfers, including overdue ones
  and ones blocked by an archived Account; UI should flag those separately.
- A future horizon variant `projected_balance(A, as_of=D)` counts only planned
  transfers with `planned_date <= D`.
- **Definition only.** No projected-balance endpoint or field is part of
  VF-018A/B/C/D/E unless separately approved.

Known semantic gap (D16, accepted): "current = posted only" is true for
transfers, but future-dated Income, base-currency Expense, and adjustment
rows still create ledger rows immediately and affect the current balance.
VF-018 does not change that; it is a separate discovery (section 29).

---

## 18. Transaction boundary / atomicity

| Operation | Single database transaction contains | Commits |
|---|---|---|
| Posted create | canonical transfer + source debit + destination credit | once |
| Planned create | canonical transfer only | once |
| Manual post | status transition (+ `effective_date`, `posted_at`) + source debit + destination credit | once |
| Delete | canonical transfer delete (+ cascaded ledger rows if posted) | once |

- Any exception rolls everything back: an explicit rollback before raising a
  domain error (the `account_service` pattern), plus the implicit rollback when
  `get_db_session` closes an uncommitted session.
- Repository functions flush and never commit on their own in these paths.
- No network I/O happens while Account locks are held (transfers never call
  FX).
- Through application service paths no half-transfer can exist: no debit
  without a credit, no credit without a debit, and no ledger rows on a planned
  transfer.

---

## 19. Lock ordering / concurrency model (D14)

### 19.1 Lock hierarchy

```text
Level 1: the canonical row, when one already exists
         (Receipt | Income | Expense | AccountTransfer) — at most one per operation
Level 2: Account rows — always in ascending UUID order
```

| Operation | Lock sequence |
|---|---|
| Transfer create (planned or posted) | Accounts ascending |
| Transfer post | Transfer `FOR UPDATE` → Accounts ascending |
| Transfer delete | Transfer `FOR UPDATE` → Accounts ascending |
| Idempotent replay | none (read only) |
| Account update / archive / delete | one Account; `account_transfers` is **read** under that lock, never locked |
| Existing Income/Expense/Receipt paths (unchanged) | canonical row → Account(s) ascending |

All existing lock-taking paths already follow this hierarchy
(`income_service.update_income` sorts two Accounts by ascending UUID, and
every path locks its canonical row before any Account). UUID sorting happens
in Python in every path, so the order is consistent across callers.

### 19.2 What the ordering guarantees

- Deterministic ordering removes the known Account lock-order cycle — for
  example transfer A→B running concurrently with transfer B→A, or a transfer
  running concurrently with an opposite-direction Income/Expense move. Both
  sides take `min(A, B)` first.
- No path takes a level-1 lock after a level-2 lock.
- Implicit FK locks (`FOR KEY SHARE` on referenced Accounts during INSERT)
  are taken by a transaction that already holds `FOR UPDATE` on those
  Accounts. Every other writer also locks the Account first.
- This is a design argument, not a proof that no PostgreSQL deadlock can ever
  occur. It must be verified by real-thread concurrency tests (section 25).
  A detected deadlock would surface as an unhandled 500, so the ordering is
  enforced by design and tests, not by an error handler.

### 19.3 Concurrency scenarios (expected outcomes)

| # | Scenario | Expected outcome |
|---|---|---|
| C1 | Create A→B ∥ create B→A (posted) | Both succeed, no deadlock, exact balances |
| C2 | Two posted creates from the same source | Both succeed, exact sum, no lost update |
| C3 | Post ∥ post of the same transfer | One 200, one 409 AlreadyPosted, exactly two ledger rows |
| C4 | Post ∥ delete of the same transfer | Either posted-then-deleted (balances restored) or deleted-then-404; never orphan ledger rows |
| C5 | Post ∥ archive source (and separately destination) | Either posted then archived, or 409 with the transfer still planned and zero rows |
| C6 | Post T1 (A→B) ∥ post T2 (B→A) | Both succeed, no deadlock |
| C7 | Transfer create/post ∥ Income or Expense move across the same Accounts | Both succeed, no deadlock, exact balances |
| C8 | Planned create ∥ currency change of a fresh Account | Either plan created + currency change 409, or currency changed + plan 422; never 500 |
| C9 | Planned create ∥ deletion of a fresh Account | Either plan created + delete 409, or Account deleted + plan 404; never 500 |
| C10 | Planned delete ∥ Account delete | Clean 409 or 204 outcomes; never 500 |
| C11 | Same `client_request_id` + same payload, concurrently | Exactly one transfer; one 201 and one 200 |
| C12 | Same `client_request_id`, different Accounts, concurrently | One 201 and one 409 via the IntegrityError path; never 500 |
| C13 | Posted create ∥ archive of either Account | Either created then archived, or 409 with nothing written |

---

## 20. Database schema direction

**Direction only. No Alembic migration is created in VF-018A.** One new
revision in VF-018B; its `down_revision` is the Alembic head at that time
(`7dd404d0d20e` when this contract was written). No data backfill.

### 20.1 `accounts`

```sql
ALTER TABLE accounts
  ADD CONSTRAINT uq_accounts_id_user_id_currency UNIQUE (id, user_id, currency);
```

This is the FK target for the currency-bearing composite FKs. The existing
`uq_accounts_id_user_id` stays for `account_transactions`.

### 20.2 `account_transfers` (new)

```sql
CREATE TABLE account_transfers (
  id                     uuid PRIMARY KEY,
  user_id                uuid NOT NULL,
  client_request_id      uuid NOT NULL,
  source_account_id      uuid NOT NULL,
  destination_account_id uuid NOT NULL,
  amount                 numeric(12,2) NOT NULL,
  currency               varchar(3) NOT NULL,
  status                 varchar(10) NOT NULL,   -- no server default; always set by the service
  planned_date           date NULL,
  effective_date         date NULL,
  description            varchar(500) NULL,
  posted_at              timestamptz NULL,
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT ck_account_transfers_amount_positive CHECK (amount > 0),
  CONSTRAINT ck_account_transfers_distinct_accounts
    CHECK (source_account_id <> destination_account_id),
  CONSTRAINT ck_account_transfers_status_valid CHECK (status IN ('planned','posted')),
  CONSTRAINT ck_account_transfers_lifecycle_consistent CHECK (
    (status = 'planned' AND planned_date IS NOT NULL
                        AND effective_date IS NULL AND posted_at IS NULL)
    OR
    (status = 'posted'  AND effective_date IS NOT NULL AND posted_at IS NOT NULL)
    -- posted: planned_date may remain non-null if the transfer began as planned
  ),

  CONSTRAINT uq_account_transfers_id_user_id UNIQUE (id, user_id),
  CONSTRAINT uq_account_transfers_user_id_client_request_id
    UNIQUE (user_id, client_request_id),

  CONSTRAINT fk_account_transfers_source_account
    FOREIGN KEY (source_account_id, user_id, currency)
    REFERENCES accounts (id, user_id, currency) ON DELETE RESTRICT,
  CONSTRAINT fk_account_transfers_destination_account
    FOREIGN KEY (destination_account_id, user_id, currency)
    REFERENCES accounts (id, user_id, currency) ON DELETE RESTRICT
);

CREATE INDEX ix_account_transfers_source_account_id      ON account_transfers (source_account_id);
CREATE INDEX ix_account_transfers_destination_account_id ON account_transfers (destination_account_id);
```

The `uq_account_transfers_user_id_client_request_id` index leads with
`user_id`, so it also serves list-by-user queries; no separate user index is
needed.

### 20.3 `account_transactions`

```sql
ALTER TABLE account_transactions ADD COLUMN transfer_id uuid NULL;

ALTER TABLE account_transactions
  ADD CONSTRAINT fk_account_transactions_transfer_id_user_id
  FOREIGN KEY (transfer_id, user_id)
  REFERENCES account_transfers (id, user_id) ON DELETE CASCADE;

ALTER TABLE account_transactions
  ADD CONSTRAINT uq_account_transactions_transfer_id_direction
  UNIQUE (transfer_id, direction);              -- at most one debit and one credit per transfer

-- replace
ck_account_transactions_kind_valid:
  kind IN ('opening_balance','adjustment','income','expense','transfer')

-- replace (4 mutually exclusive branches)
ck_account_transactions_source_linkage_valid:
     (kind = 'income'   AND income_id IS NOT NULL   AND expense_id IS NULL
                        AND transfer_id IS NULL     AND direction = 'credit')
  OR (kind = 'expense'  AND expense_id IS NOT NULL  AND income_id IS NULL
                        AND transfer_id IS NULL     AND direction = 'debit')
  OR (kind = 'transfer' AND transfer_id IS NOT NULL AND income_id IS NULL
                        AND expense_id IS NULL)
  OR (kind IN ('opening_balance','adjustment')
                        AND income_id IS NULL AND expense_id IS NULL AND transfer_id IS NULL)
```

`ON DELETE CASCADE` on `transfer_id` follows the Income/Expense precedent: the
canonical record owns its projections.

### 20.4 Security statements in the same migration

An explicit, `pg_roles`-guarded
`REVOKE ALL PRIVILEGES ON TABLE public.account_transfers FROM anon,
authenticated, service_role` (a no-op locally and in CI). See section 22.

### 20.5 Downgrade

`DELETE FROM account_transactions WHERE kind = 'transfer'` first, then
reverse every step: restore the 3-branch linkage CHECK and the 4-value kind
CHECK, drop the transfer FK/unique/column, drop `account_transfers`, drop
`uq_accounts_id_user_id_currency`. The downgrade permanently loses all
transfer data (planned and posted). This is documented in the migration
docstring, in the style of `811506d8afd2` / `7dd404d0d20e`.

### 20.6 No triggers

No trigger, deferred constraint trigger, or generated-column FK is
introduced. Both alternatives were evaluated and rejected as new schema
patterns with marginal benefit (section 21).

### 20.7 Test infrastructure implication

`tests/conftest.py::clean_database` must delete `AccountTransferModel` rows
after `AccountTransactionModel` and before `AccountModel`.

---

## 21. Database vs service invariants

| Invariant | Enforced by |
|---|---|
| Valid status | DB CHECK |
| Lifecycle/date consistency (planned: planned_date set, no effective_date/posted_at; posted: effective_date + posted_at set) | DB CHECK |
| amount > 0 | DB CHECK + schema |
| source ≠ destination | DB CHECK + schema |
| Both Accounts and the transfer share one owner | DB composite FKs |
| Source, destination, and transfer share one currency | DB composite FKs + service check (create, post) |
| Referenced Account cannot be deleted or change currency | DB FK (last line) + service 409 (section 11) |
| At most one debit and one credit row per transfer | DB UNIQUE `(transfer_id, direction)` |
| A transfer row is never also an Income/Expense row | DB linkage CHECK |
| Projection ownership matches the transfer | DB composite FK `(transfer_id, user_id)` |
| One create per `(user_id, client_request_id)` | DB UNIQUE |
| `planned_date > today` at create; `effective_date <= today` | Service (depends on server date; not expressible as an immutable CHECK) |
| **Planned transfer has zero ledger rows** | Service: `create_transfer_projections` guard on `status == 'posted'`, called only from posted create and post |
| **Posted transfer has exactly two correct rows** (debit on source, credit on destination, amount = transfer.amount, transaction_date = effective_date) | Service atomicity + single two-row primitive + no per-row update/delete primitive; supported by DB uniqueness/linkage and integrity tests |
| Only `planned -> posted` | Service: a single transition function |
| Account balance never stored | Existing design (no balance column) |

Integrity reconciliation queries (used by integration tests and the
production deployment checklist). Both must return zero rows:

```sql
-- Posted transfers with missing or inconsistent ledger rows
SELECT t.id
FROM account_transfers t
LEFT JOIN account_transactions d ON d.transfer_id = t.id AND d.direction = 'debit'
LEFT JOIN account_transactions c ON c.transfer_id = t.id AND c.direction = 'credit'
WHERE t.status = 'posted'
  AND (   d.id IS NULL OR c.id IS NULL
       OR d.account_id <> t.source_account_id
       OR c.account_id <> t.destination_account_id
       OR d.amount <> t.amount OR c.amount <> t.amount
       OR d.transaction_date <> t.effective_date
       OR c.transaction_date <> t.effective_date);

-- Planned transfers that have any ledger row
SELECT t.id
FROM account_transfers t
WHERE t.status = 'planned'
  AND EXISTS (SELECT 1 FROM account_transactions x WHERE x.transfer_id = t.id);
```

Rejected alternatives:

- a deferred constraint trigger enforcing "exactly two rows" — a new trigger
  architecture (the repository has no triggers);
- a generated-column FK forcing legs to reference only posted transfers, or
  two leg columns with conditional FKs — new schema patterns with marginal
  benefit that still cannot prevent a missing leg; atomicity already covers
  that.

---

## 22. Supabase Data API security requirement

- `account_transfers` will be the **first new business table created after
  VF-SEC-01** (`edcfdf3f7114`). VF-SEC-01 revoked existing table privileges
  and the `postgres` role's default privileges for future tables, but that
  default-privilege revocation has never yet been exercised in production by
  a new table.
- The VF-018B migration must therefore explicitly ensure that application
  Data API roles (`anon`, `authenticated`, `service_role`) gain no access: a
  `pg_roles`-guarded `REVOKE ALL PRIVILEGES` on `public.account_transfers`.
  Do not edit the already-applied VF-SEC-01 migration.
- A unit test asserts the new migration contains the guarded REVOKE for all
  three roles and targets the new table explicitly (never a schema-wide
  statement).
- FastAPI remains the only business-data gateway; mobile never touches this
  table through the Supabase Data API.

Production deployment checklist for VF-018B (future; nothing is performed in
VF-018A):

1. New production backup before the migration (schema-changing).
2. `alembic upgrade head`.
3. Data API privilege verification — every value must be `false`:
   ```sql
   SELECT r.rolname,
          has_table_privilege(r.rolname, 'public.account_transfers', 'SELECT') AS can_select,
          has_table_privilege(r.rolname, 'public.account_transfers', 'INSERT') AS can_insert,
          has_table_privilege(r.rolname, 'public.account_transfers', 'UPDATE') AS can_update,
          has_table_privilege(r.rolname, 'public.account_transfers', 'DELETE') AS can_delete
   FROM pg_roles r
   WHERE r.rolname IN ('anon', 'authenticated', 'service_role');
   ```
4. Transfer integrity verification (section 21 queries return zero rows).
5. Observe and record the Render process timezone (expected UTC; section 6).

---

## 23. API contract direction

All endpoints require authentication (`CurrentUser`; `X-User-Id` in
development mode only). Router prefix `/account-transfers`, mounted under
`/api/v1`.

| Method | Path | Success | Purpose |
|---|---|---|---|
| POST | `/api/v1/account-transfers` | 201 (create) / 200 (identical replay) | Create a planned or posted transfer |
| GET | `/api/v1/account-transfers` | 200 | List all of the user's transfers (planned and posted) |
| POST | `/api/v1/account-transfers/{id}/post` | 200 | Manually post a planned transfer |
| DELETE | `/api/v1/account-transfers/{id}` | 204 | Hard-delete a planned or posted transfer |

There is no PATCH and no `GET /{id}` (consistent with Accounts/Goals; add one
only if later justified).

### 23.1 Create request (`extra="forbid"`)

```json
{
  "client_request_id": "0f8c5f5e-6a38-4a8e-9b0e-2f7d0a6f1c11",
  "source_account_id": "uuid",
  "destination_account_id": "uuid",
  "amount": "300.00",
  "transfer_date": "2026-10-15",
  "description": "Move to savings"
}
```

| Field | Rules |
|---|---|
| `client_request_id` | UUID, required |
| `source_account_id` | UUID, required |
| `destination_account_id` | UUID, required, must differ from source (422) |
| `amount` | Decimal, required, `gt=0`, `max_digits=12`, `decimal_places=2` (max `9999999999.99`) |
| `transfer_date` | date, required, no lower bound; classified per section 7 |
| `description` | optional, max 500 chars |

Rejected as extra fields (422): `user_id`, `currency`, `status`, `kind`,
`planned_date`, `effective_date`, `posted_at`.

### 23.2 Post request (`extra="forbid"`, body optional)

```json
{ "effective_date": "2026-10-18" }
```

| Field | Rules |
|---|---|
| `effective_date` | optional date; default `today`; must be `<= today` (422); may be before or after `planned_date` |

### 23.3 `AccountTransferResponse`

```text
id                      UUID
user_id                 UUID
client_request_id       UUID
source_account_id       UUID
destination_account_id  UUID
amount                  Decimal   (serialized as a string)
currency                str
status                  "planned" | "posted"
planned_date            date | null
effective_date          date | null
description             str | null
posted_at               datetime | null
created_at              datetime
updated_at              datetime
```

### 23.4 List ordering

`COALESCE(effective_date, planned_date) DESC, created_at DESC, id DESC`. No
filters or pagination in the MVP (consistent with existing list endpoints;
clients filter planned/posted locally).

### 23.5 `AccountTransactionResponse` additions

`kind` gains `"transfer"`; new nullable `transfer_id` and
`counterparty_account_id` (section 16).

---

## 24. Error model

New domain errors are mapped centrally in `app/core/exception_handlers.py`.
Detail strings are the intended wording.

| Error | HTTP | Detail | Raised when |
|---|---|---|---|
| Schema validation (amount, same Account, extra fields, missing `client_request_id`) | 422 | FastAPI/Pydantic default | Request body invalid |
| `AccountNotFoundError` (existing) | 404 | "Account not found." | Either Account missing or foreign |
| `AccountArchivedError` (existing) | 409 | "Archived account cannot receive new transactions." | Create or post with an archived Account |
| `AccountTransferNotFoundError` (new) | 404 | "Account transfer not found." | Post/delete of a missing or foreign transfer |
| `AccountTransferCurrencyMismatchError` (new) | 422 | "Transfer source and destination accounts must use the same currency." | Currencies differ (create; defensively at post) |
| `AccountTransferAlreadyPostedError` (new) | 409 | "Account transfer has already been posted." | Post of a non-planned transfer |
| `AccountTransferEffectiveDateInFutureError` (new) | 422 | "Transfer effective date cannot be in the future." | Post with `effective_date > today` |
| `AccountTransferIdempotencyConflictError` (new) | 409 | "client_request_id has already been used for a different transfer." | Same key, different payload |
| `AccountReferencedByPlannedTransferError` (new, accounts domain) | 409 | "Account is referenced by planned transfers. Delete them first." | Account delete or currency change while referenced by a planned transfer |
| `AccountCurrencyImmutableError` / `AccountDeletionNotAllowedError` (existing) | 409 | unchanged | Account with ledger history (including transfer rows) |

Internal only (never mapped to HTTP): the client-request-id unique-violation
signal used by the concurrent-duplicate path (section 10.5), and the
`ValueError` raised by the projection primitive guard.

There is intentionally **no "not yet due" error**: early posting is allowed
(D12).

---

## 25. Test matrix

All backend tests run only against a dedicated `*_test` database
(VF-TEST-01). Concurrency tests use real threads, separate sessions, and
`threading.Barrier` (existing pattern). Date-dependent tests pass an explicit
`as_of` / use relative dates with margins, never calling `date.today()`
twice across an assertion boundary.

### 25.1 Schema (unit)
- Amount limits (`0`, negative, 13 digits, 3 decimals rejected;
  `9999999999.99` accepted).
- `source == destination` → 422.
- Missing `client_request_id` → 422.
- Extra fields (`currency`, `status`, `user_id`, `kind`, `planned_date`,
  `effective_date`) → 422.
- Description > 500 → 422.
- Post body: extra fields rejected; empty body accepted.

### 25.2 Classification and date semantics
- `transfer_date` = yesterday → posted, `planned_date=NULL`,
  `effective_date=transfer_date`, `posted_at` set, two rows dated
  `effective_date`.
- `transfer_date` = today (boundary via `as_of`) → posted.
- `transfer_date` = tomorrow → planned, `effective_date=NULL`,
  `posted_at=NULL`, **zero ledger rows**, balances unchanged, absent from
  history, present in list.

### 25.3 Manual posting
- Omitted `effective_date` → `as_of`; explicit past date; date **before**
  `planned_date` (early); date **after** `planned_date` (late) → posted,
  `planned_date` preserved, rows dated `effective_date` (not `planned_date`),
  balances updated, visible in history.
- Future `effective_date` → 422; transfer stays planned with zero rows.
- Already posted → 409.
- Foreign or missing transfer → 404.
- Source archived / destination archived → 409; stays planned, zero rows,
  balances unchanged; after reactivation → post succeeds.
- Injected failure after the status update → full rollback (planned, zero
  rows).

### 25.4 Create validation
- Foreign or missing source/destination → 404 (both planned and posted).
- Archived source/destination → 409 (both planned and posted).
- Currency mismatch → 422 (both planned and posted).
- Negative resulting balance allowed.
- Injected failure after the transfer insert → nothing persisted, balances
  unchanged.

### 25.5 Idempotency
- Identical replay → 200, same `id`, one row, no extra ledger rows, balances
  unchanged.
- Replay after planned → posted → 200 with `status=posted`.
- Replay after an Account was archived → 200 (no business revalidation).
- Conflict on each field (source, destination, amount, date, description) →
  409, nothing written.
- `"300"` vs `"300.00"` treated as identical.
- Same UUID used by two users → two independent 201s.
- Concurrent duplicates (C11, C12).
- Retry after DELETE creates a new transfer (documented accepted behavior).
- Direct INSERT violating `UNIQUE(user_id, client_request_id)`.

### 25.6 Delete
- Planned → removed, ledger untouched.
- Planned with an archived Account → allowed.
- Posted → both rows cascaded, balances restored.
- Foreign → 404.
- Retry → 404.

### 25.7 Account lifecycle interaction
- Account delete / currency change while referenced by a planned transfer →
  409 `AccountReferencedByPlannedTransferError` (never 500); allowed after the
  planned transfer is deleted.
- Archive while referenced by a planned transfer → allowed; the transfer
  stays planned.
- Account with a posted transfer → existing 409 history errors; allowed again
  after the transfer is deleted and no other history remains.

### 25.8 Database constraints (direct INSERT/UPDATE)
- Each CHECK: amount, distinct accounts, status, lifecycle (planned with
  `effective_date`; planned without `planned_date`; posted without
  `effective_date`; posted without `posted_at`).
- Cross-user source/destination FK; currency-mismatch FK; currency UPDATE on
  a referenced Account blocked; Account DELETE while referenced blocked.
- Duplicate `(transfer_id, direction)`; transfer row with
  `income_id`/`expense_id`; `transfer_id` on a non-transfer kind; cross-user
  `transfer_id` FK.
- Repository guard: `create_transfer_projections` on a planned transfer →
  `ValueError`.

### 25.9 Read model
- History shows both sides with `transfer_id` and the correct
  `counterparty_account_id`; planned is never shown.
- Counterparty resolved without per-row queries.
- Transfer list ordering and user isolation; router response shapes.

### 25.10 Invariants and non-impact
- The sum of a user's Account balances in one currency is unchanged by
  planned create, posted create, post, and delete.
- Reconciliation queries (section 21) return zero rows after every lifecycle
  test.
- Analytics unchanged: monthly summary, category summary, budget status,
  spending trend, category trends, forecast, and goal progress are identical
  before and after planned and posted transfers; no Income/Expense rows are
  created.

### 25.11 Concurrency
- C1–C13 (section 19.3), including post/post, post/delete, opposite-direction
  transfers, and interaction with Income moves.

### 25.12 Migration / security
- Exactly one Alembic head; the VF-SEC-01 revision is still in its ancestry;
  the new revision chains onto the head at implementation time.
- The new migration contains a `pg_roles`-guarded REVOKE for `anon`,
  `authenticated`, and `service_role` targeting `public.account_transfers`
  explicitly (no schema-wide statement).
- Upgrade/downgrade run cleanly on the test database.

---

## 26. Mobile follow-up requirements (VF-018E, D19)

Read `apps/mobile/AGENTS.md` and the Expo SDK 57 documentation first.

- **Types:** `AccountTransactionKind` gains `"transfer"`;
  `AccountTransaction` gains `transfer_id` and `counterparty_account_id`
  (`string | null`); new `AccountTransfer` type mirroring
  `AccountTransferResponse`, with money kept as strings.
- **Service:** create/list/post/delete through the feature service and
  `src/api/api-client.ts`. No Supabase Data API access.
- **Idempotency key:** generate `client_request_id` with `expo-crypto`
  `randomUUID()` (a new Expo SDK dependency to be verified against SDK 57 docs
  and installed with `npx expo install`). One key per create confirmation
  flow; reuse it on retries; regenerate after success or when the form closes.
  Keep submit disabled while pending (UX only).
- **Create form:** source = active Accounts only; destination = active
  Accounts in the same currency, excluding the source; amount validated as a
  string (never `Number(...)`/`parseFloat(...)`); date defaulting to today; a
  future date shows "will be planned" (the server decides). Confirmation step
  before submit.
- **Account picker:** do not repeat the known Income picker issue — do not
  hide the picker on a query error when cached data exists, and never submit a
  hidden selection.
- **History:** label "Transfer to {name}" / "Transfer from {name}" from the
  cached Account list, falling back to "Transfer"; sign from `direction`.
- **Planned transfers:** a planned section (per Account and/or global) with
  "Due" (`planned_date <= today`) and "Blocked" (an archived side) badges; a
  Post action with a confirmation dialog that always sends an explicit
  `effective_date` (default today); delete with confirmation.
- **Error handling:** clear messages for 404, 409 (archived, already posted,
  idempotency conflict, planned reference), and 422 (currency, future
  effective date, validation). 409 AlreadyPosted → refetch. 404 on delete →
  success.
- **Query invalidation (affected families only):** after posted create, post,
  or posted delete — Accounts list, both Accounts' transaction histories, and
  the transfers list; after planned create or planned delete — the transfers
  list only. Never income, expenses, analytics, budgets, or goals.
- **No projected balance UI** until separately approved.

---

## 27. Analytics non-impact

- `analytics`, `budgets`, and `goals` modules do not read `account_transactions`
  (verified at the time of writing), and transfers never create Income or
  Expense rows. Monthly summary, category summary, budget status, spending
  trend, category trends, forecast, and goal progress are therefore
  structurally unaffected by both planned and posted transfers.
- No analytics code changes in VF-018.
- Future true cash-flow analytics may distinguish external flows
  (Income/Expense) from internal transfers; that is a separate feature.
- Transfers must not interact with Goals. GoalTransaction remains separate;
  there is no Account ↔ Goal movement.

---

## 28. Explicit out-of-scope

- Automatic scheduler / background posting
- Recurring transfers
- PATCH (including rescheduling a plan)
- Unpost / reversal entities
- Audit / tombstone system
- FX transfers (different currencies)
- Cross-user transfers
- Goal ↔ Account integration of any kind
- Projected-balance endpoint or field
- Planned Income
- Planned Expense
- Planned Adjustment redesign
- User timezone implementation
- Receipt/OCR work
- Web client
- Analytics changes

---

## 29. Known follow-ups

- **Server vs user timezone gap** (D13): "today" is the server date (expected
  UTC). A per-user timezone (for example in `user_financial_settings`) is a
  planner follow-up. The FX future-dated rule shares the same gap.
- **Future planner expansion:** planned/due views, horizon-based projections.
- **Planned Income/Expense semantics** (D16): future-dated Income,
  base-currency Expense, and adjustment rows currently hit the current balance
  immediately; needs separate discovery before any planner relies on
  "current = posted only" globally.
- **Projected-balance API** (D15): the definition exists; the endpoint/field
  needs separate approval.
- **Stronger persistent idempotency / tombstones** (D18): would close the
  post-delete key-reuse residual risk (section 10.6).
- **Automatic scheduler** for posting due planned transfers.
- **Recurring transfers.**

---

## 30. Implementation slicing

Each slice is a separate branch created from an up-to-date `main` after the
previous slice is merged. Nothing below is implemented yet.

| Slice | Scope |
|---|---|
| **VF-018A** | This contract document. |
| **VF-018B** | Schema/domain foundation: `account_transfer_models.py`; the migration (section 20), including the guarded REVOKE; repository primitives (transfer create/read/lock/delete, `create_transfer_projections` with the status guard); AccountTransaction transfer linkage in the model (`transfer_id`, kind, CHECKs) and in `AccountTransactionResponse` (`kind` accepts `transfer`, `transfer_id` exposed — so history never breaks once a transfer row can exist); model registration; `clean_database` update; DB constraint tests; migration/security tests; `docs/database-schema.md`. No endpoints. Requires a production backup before deployment and the section 22 checklist. |
| **VF-018C** | Create (planned + posted, with idempotency), list, delete; planned-reference Account protections (section 11) — these must ship together with the first ability to create a planned transfer; `counterparty_account_id` history read model; service/router/idempotency tests; concurrency C1, C2, C7–C13; analytics non-impact and balance-sum tests; `docs/api-contract.md` and `docs/architecture.md` updates. |
| **VF-018D** | Manual posting endpoint (`POST /{id}/post`); posting concurrency C3–C6; documentation updates. |
| **VF-018E** | Mobile planned/posted transfers (section 26). |
| Later | Planner, projected balance, user timezone, planned Income/Expense, scheduler, recurring transfers — each only after separate approval. |

---

## 31. Decision record (approved)

| ID | Decision |
|---|---|
| D1 | Canonical `account_transfers` entity + two ledger projections `kind='transfer'` linked by `transfer_id`; the canonical row also holds planned state. |
| D2 | Same-currency only; currency is server-derived, protected by composite FKs, checked at create and at post. No FX. |
| D3 | Archived Account: create rejected on either side; archiving while planned transfers exist is allowed; posting with an archived side → 409 and the transfer stays planned; deleting planned or posted transfers with an archived side is allowed. |
| D4 | Negative Account balance allowed; no insufficient-funds validation. |
| D5 | API: POST create, GET list, POST `/{id}/post` (optional `effective_date`), DELETE. No PATCH, no GET-by-id. |
| D6 | Hard delete: planned → canonical row only; posted → canonical row + cascaded ledger rows; `client_request_id` is freed. No reversal. |
| D7 | Create `transfer_date <= today` → posted with `effective_date = transfer_date`; `> today` → planned with `planned_date = transfer_date` and no ledger rows. |
| D8 | Account history shows only posted transfer rows, dated `effective_date`, with `transfer_id` and `counterparty_account_id`, resolved without N+1. |
| D9 | Server-side create idempotency via required `client_request_id` (D18); client submit-disabling is UX only. |
| D10 | Implementation lives inside `app/modules/accounts/` (`account_transfer_*` files) with a separate `/account-transfers` router. |
| D11 | Status `planned` \| `posted`, server-derived, forward-only; `posted_at` technical timestamp; DB lifecycle CHECK including date fields. |
| D12 | Manual posting at any time while planned (early or late); `effective_date` optional, default today, must be `<= today`; no "not due" rule; no scheduler; overdue plans stay planned. |
| D13 | "today" = server date via an `as_of` seam (same notion as the FX rule); timezone gap documented as a planner follow-up; mobile sends `effective_date` explicitly. |
| D14 | An Account referenced by a planned transfer cannot be deleted or change currency → 409 `AccountReferencedByPlannedTransferError`; create locks both Accounts even for planned. |
| D15 | `projected_balance = current_balance + planned_incoming − planned_outgoing` (all planned, including overdue/blocked; horizon by `planned_date`); definition only, no endpoint. |
| D16 | Accepted known gap: future-dated Income/Expense/adjustment rows still affect the current balance; separate discovery. |
| D17 | Date model: `planned_date` (immutable), `effective_date` (ledger accounting date), `posted_at` (technical); no `transfer_date` column. |
| D18 | Idempotency: `client_request_id` UUID body field, required, `UNIQUE(user_id, client_request_id)`; identical replay → 200 with current state and no business revalidation; different payload → 409; concurrent duplicate resolved through the IntegrityError path; key freed on hard delete (accepted residual risk). |
| D19 | Mobile generates the key with `expo-crypto` `randomUUID()` (new Expo SDK dependency, verified against SDK 57 docs in VF-018E); one key per create confirmation flow. |
