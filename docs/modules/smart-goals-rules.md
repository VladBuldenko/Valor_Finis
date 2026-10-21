# VF-020A — Smart Goals & Rules: Product & Technical Contract

**Status: VF-020A — APPROVED FOR DOCUMENTATION / IMPLEMENTATION PLANNING**

**Implementation is not authorized by this document alone.** This document
approves no migration, no VF-020B…F implementation, no production-data access,
no external bank integration and no deployment. Each of those requires its own
explicit authorization.

---

## 1. Document Metadata and Approval Status

| | |
|---|---|
| Contract version | v0.6 (VF-020E1 rules-engine finalization), approved for documentation / implementation planning |
| Approval date | 2026-10-05 (v0.3); 2026-10-07 (v0.4 VF-020C decisions P58, P60–P66); 2026-10-13 (v0.5 VF-020D decisions P67–P77); 2026-10-16 (v0.6 VF-020E decisions P78–P88 and approval of P28, P31, P37, P42, P52, P53, P57) |
| Baseline | v0.6: `main` @ `a81c017fb7542f6f54b022dbc2facf01c7c1ca42` (after VF-020D5, PR #83). Earlier versions: v0.5 `146451577eb63501dcde54942021148d90278710`; v0.3 `635ea7506f50f4df669c569a7407fd356ef0b790` |
| History | v0.1 draft (2026-10-03) → v0.2 revision (2026-10-03) → v0.3 consolidated (2026-10-04) → approval of the remaining product decisions (2026-10-05) → v0.4 VF-020C finalization after discovery against `main` @ `ad42baf` (2026-10-07) → v0.5 VF-020D finalization (Goal priorities and L0) after discovery against `main` @ `146451577eb63501dcde54942021148d90278710` (2026-10-13) → v0.6 VF-020E1 finalization of the rules-engine contract after discovery (VF-020E0, VF-020E0R) against `main` @ `a81c017fb7542f6f54b022dbc2facf01c7c1ca42` (2026-10-16) |
| Scope | VF-020 Smart Goals & Rules. VF-021 Financial Connections & Import is a separate milestone (§22) |
| Implementation state | **Current production schema revision: `861064d31463`** (VF-020E4, applied to production 2026-10-21; earlier: `115998e2e795` VF-020E2 on 2026-10-19, `7c1e5a9b3d28` D5). History by stage follows. VF-020B (Goals hardening, B1–B4) was implemented and applied to production (revision `8799b7fd923d` at that time). The VF-020C1 schema-expand migration (`98acdc7016d2`, nullable `goal_transactions.account_id`) is applied to production. **VF-020C2 (backend runtime) is merged and deployed** (no new migration): ORM mapping, tracked/linked partitions, linked contributions and withdrawals, the Account capacity read model, Goal `tracked_amount`/`linked_amount`/`allocations`, Account delete/currency protection and the approved 404/409/422 precedence. **VF-020C3 (mobile) is merged** (PR #78; `main` @ `146451577eb63501dcde54942021148d90278710` contains C3; independent strict review PASS; physical-device acceptance cases A-M recorded as user-confirmed PASS with no blocking UI defect; no local proxy or database evidence and no automated or log evidence is attached to that record): tracked vs linked contribution source ("Reserve from account"), an explicit withdrawal partition choice that is never preselected, Goal "Reserved in accounts" / allocations and Account "Reserved for goals" / "Available to reserve" displays, Reservation / Release history labels, `account_id` in the screen-local idempotency attempt, and targeted cache invalidation (an Account refresh only for linked operations). Acceptance confirmed: a reservation does not change the Account's `current_balance`; Account reserved/reservable amounts and the Goal tracked/linked/allocation values refresh after an operation; a withdrawal always needs an explicit partition; an archived Account's partition stays releasable while the Account is excluded from new reservations; the error UX shows controlled messages; and a dropped-response retry replays the original transaction. Reservations earmark money and never move it. Not implemented in C3, by design (historical statement as of C3; priorities and L0 were implemented later by VF-020D): FX reservations, partial allocation, safety floor, AUTO/CONFIRM rules, priorities, advisory L0 and persistent idempotency storage. Known residual (inherited from B3): the idempotency attempt lives in the open Goal form, so if a response is lost and the user leaves the Goal form before retrying, the screen-local `client_request_id` may be lost. **VF-020D (Goal priorities and the user lock L0) is COMPLETE** (contract v0.5, decisions P67–P77): D2 expand migration `4d2f7b91a6c3` applied to production (nullable `priority_rank`, `>= 1` CHECK, deferrable `UNIQUE (user_id, priority_rank)`, deterministic backfill); D3 backend runtime merged (PR #81: `priority_rank` on `GoalResponse`, priority-aware canonical `GET /goals` order, `PUT /api/v1/goals/priorities`, and the user advisory lock L0 on every Goal write, §14.5); D4 mobile Priorities screen merged (PR #82); D5 contract migration `7c1e5a9b3d28` merged (PR #83) and applied to production (lifecycle CHECK `ck_goals_priority_rank_lifecycle`, `(status = 'archived') = (priority_rank IS NULL)`). **Production schema revision (supplied project state): `7c1e5a9b3d28`.** **VF-020E (rules engine, outbox, AUTO, CONFIRM, floor, alerts, backend) has its contract finalized here (v0.6, VF-020E1, decisions P78–P88 and the approval of P28, P31, P37, P42, P52, P53, P57) and is only PARTIALLY implemented (outbox schema and Income outbox writes; no rules, AUTO or CONFIRM)**: E1 (contract) is merged. **VF-020E2 is COMPLETE**: the `financial_events` schema expand (revision `115998e2e795`, `down_revision` `7c1e5a9b3d28`) is merged and applied to production on 2026-10-19; the table is active and empty in production, with no foreign keys and no Data API privileges. **VF-020E3 (Income outbox runtime) is MERGED** (PR #86; `main` @ `899e11b15a988f2ea926a449e7380bde6b6d9811`; no migration; its runtime requires and relies on the E2 production schema): every successful manual Income create, update and delete writes one `financial_events` row (`income.created` / `income.updated` / `income.deleted`) in the same database transaction as the mutation; new events stay `pending` with `attempts = 0`. **E3 does not process events**: there is no dispatcher, claim, retry, rules lookup, Goal write, AUTO, CONFIRM, execution or event API. **VF-020E4 (rules schema expand, revision `861064d31463`, `down_revision` `115998e2e795`) is COMPLETE and applied to production** (2026-10-21; one transaction; `financial_rules` and `financial_rule_goal_targets` created empty, `uq_budgets_id_user_id` added, no Data API privileges on the new tables). **VF-020E5 (rules CRUD and safety-floor runtime) is MERGED** (PR #88, `main` @ `becc494dc38c4cf4f2c96ad7000bf178b5e0ad1a`, backend CI success, no migration): it maps the two E4 tables, adds `/api/v1/financial-rules` CRUD with enable / pause / disable, rule versioning, the floor runtime (`minimum_unallocated_floor` on `AccountResponse`), the additive manual floor `warnings` on the POST Goal-transaction response, and the controlled-409 lifecycle pre-checks for Goals, Accounts and Budgets referenced by rules. Income-allocation and alert rules stay drafts in E5. **VF-020E6 (execution schema expand, revision `e0503e9ca9d3`, `down_revision` `861064d31463`) is implemented on the local feature branch `feat/VF-020E6-execution-schema` and is NOT pushed, merged or applied to production; production stays at `861064d31463`.** E6 creates `rule_executions`, `rule_execution_items` and `rule_execution_audit`, the PostgreSQL sequence `rule_execution_hold_sequence`, `goal_transactions.rule_execution_id` with the broadened linked-origin CHECKs, and `UNIQUE (id, user_id)` on `goal_transactions`. The application neither reads nor writes the new objects: the new `goal_transactions` column is deliberately not ORM-mapped until the E7 runtime. **E7 (AUTO, event processing, dispatcher, execution creation), E8 (CONFIRM), the alert runtime and all mobile work are not started.** **VF-020F (mobile for rules, proposals, Inbox and the floor warning) is not started.** The semantics of P58 and P60–P66 are unchanged by the implementation, except that P61 is superseded by P68 |

Status tags used throughout:

| Tag | Meaning |
|---|---|
| **APPROVED** | Explicitly accepted by the user. |
| **ESTABLISHED (EST)** | Proven existing behavior at the baseline. |
| **PROPOSED** | Architectural recommendation; not binding until approved. |
| **UDR** | Unresolved user decision. |
| **EXT** | External, legal, provider or platform verification required. |

A PROPOSED item that refines an APPROVED decision does not inherit its approval.

---

## 2. Executive Summary

**VF-020 Smart Goals & Rules** works only on data already recorded in Valor
Finis (manual Income, Expenses, Accounts, Transfers, Receipts). It defines:

- **Model B + C (APPROVED):** account-linked Goal reservations alongside
  independent tracked-only Goal progress. A reservation never moves money and
  never writes an `AccountTransaction`.
- **An as-of-today capacity model (APPROVED P36, P49):** future credits never
  create capacity; recorded future debits and planned outgoing Transfers reduce
  it; `current_balance` is unchanged.
- **Goal priorities (implemented, VF-020D):** rank on every non-archived Goal, `PUT /api/v1/goals/priorities` and the user lock L0 (§9, §14.5).
- **A typed Rules Engine:** every internal allocation rule offers `AUTO` and
  `CONFIRM` (APPROVED P01) and never moves external money (APPROVED P16).
  Percentage rules use `Income.amount` (APPROVED P44). Pending `CONFIRM`
  proposals hold capacity softly (APPROVED P55) and expire after 7 days
  (APPROVED P54). The Account safety floor is strict for rules and
  warning-only for manual reservations (APPROVED P56); the floor itself is a
  `MINIMUM_UNALLOCATED_FLOOR` rule (APPROVED P78) and, with its warning, arrives
  in VF-020E (APPROVED P60).
- **Durable, database-backed event delivery:** a transactional outbox plus a
  dispatcher, idempotent executions, deterministic ordering under concurrency,
  and explicit provenance so that historical entries and imports never trigger
  `AUTO` (manual live window of 7 days, APPROVED P51). Unattended `AUTO` may be
  presented as guaranteed only once a durable periodic dispatcher exists
  (APPROVED P50).
- **Alerts that observe the existing Budgets.** Budgets remain the only
  authority for spending limits.

**VF-021 Financial Connections & Import** (consent-driven external data,
normalization, reconciliation, canonical integration) is a separate strategic
stream. Its discovery may proceed in parallel; implementation is gated on
provider, legal, privacy and security readiness, and it does not depend on the
VF-020 sequence.

**Resolved design requirements:** F1 durable trigger delivery (§12), F2 an
execution state machine with no retry/uniqueness contradiction (§13), F3
deterministic rule order under concurrency (§14), F4 provenance excluding
historical import and historical manual entries (§16).

**No user decision blocks the VF-020 product semantics.** The remaining
PROPOSED items are technical refinements finalized within their stages (§4);
VF-021 items remain UDR/EXT.

---

## 3. Approved Decisions

| ID | Approved content |
|---|---|
| P01 | Every supported internal allocation rule offers `AUTO` and `CONFIRM`. `AUTO` creates only authorized internal reservations; `CONFIRM` creates a proposal that requires explicit user approval. Neither initiates external payments. |
| P02 | Financial model = **B** (account-linked reservation) + **C** (tracked-only progress). A reservation does not transfer money; a tracked contribution makes no claim about money held in an Account. |
| P03 | Linking is per GoalTransaction, not a permanent mode of the whole Goal. |
| P04 | A new reservation above the permitted capacity is rejected with **409**; no partial write. |
| P05 | Expenses and Transfers are never blocked by reservations; underfunding is shown as `overcommitted`; Goal history is never silently rewritten. |
| P06 | Linked reservations require exact Goal/Account currency equality; no FX reservations in VF-020. |
| P07 | Withdrawals name their partition (tracked, or one specific Account-linked reservation); every partition stays nonnegative. |
| P09 | Archived Account: historical reservations kept; new linked contributions rejected; releases allowed; existing lifecycle invariants preserved. |
| P10 | Archived Goal: new contributions rejected; withdrawals and releases allowed; history preserved. This **intentionally changes** today's permissive behavior and requires explicit regression coverage. |
| P11 | Completed Goal: manual status semantics and currently permitted operations preserved; no automatic status or funding change. |
| P12 | Legacy GoalTransactions stay unchanged and unlinked; no invented Account associations. *(Also EST.)* |
| P13 | New GoalTransactions get an explicit `effective_date`: default = the current supported business date; future dates rejected; existing rows untouched; legacy rows without it keep their original meaning; `created_at` ≠ `effective_date`. |
| P14 | Every new Goal money-changing operation is idempotent, including tracked contributions and withdrawals, with an explicit transition plan for existing clients. Exactly-once is not claimed for legacy requests without a stable idempotency key. |
| P15 | Terminology: Recorded balance · Balance as of today · Reserved · Unallocated · Reservable · Overcommitted. Unallocated money is never called a guaranteed bank-available balance. |
| P16 | Internal rules never initiate real banking payments or Transfers. |
| P18 | Goals hardening ships separately and before the Goal allocation integration. |
| P19 | Integrity enforced by the database where feasible (composite FKs, consistent ownership, currency equality), with historical data verified before constraints and no invented history. **No migration is approved by this decision alone.** |
| P29 | Configurable partial allocation, default `allow_partial = false`. When false: all-or-nothing per rule; insufficient capacity yields `skipped` with an explicit reason. When true: partial execution in the approved deterministic order, recording exactly what was allocated, idempotently. |
| P35 | Rules act only on eligible Income: owned by the user; linked to the configured source Account; not future-dated; matching currency; within the rule's effective period; `refund` excluded by default; source Account and Goals eligible; duplicate processing cannot duplicate allocations. **Income has no posted/confirmed status, and none is invented.** |
| P36 | Capacity uses an as-of-today balance; future credits excluded; recorded future debit obligations subtracted (conservative); `current_balance` semantics unchanged. |
| P44 | Percentage-based Income allocation uses `Income.amount` in the matching Account/Goal currency, never `base_amount`. It applies only where the Income, the source Account and every target Goal satisfy the same-currency rule. |
| P45 | `Decimal`; allocation amounts use `ROUND_DOWN` to 0.01; the fractional remainder stays unallocated; authorized capacity is never exceeded. Financial Overview rounding is unchanged. |
| P46 | Enabling a rule never executes it retroactively over old Income. Historical bank backfill never generates automatic reservations merely because the related canonical Income is newly created. |
| P47 | Income corrections or deletion never undo, rewrite or reverse Goal transactions. Instead: executed history is preserved, current capacity recalculated, overcommitment and floor violations detected, the changed source state recorded, the user notified, and an explicit corrective release is available. |
| P48 | Precedence: (1) ownership and hard financial invariants → (2) capacity and safety floor → (3) rule order → (4) Goal priority → (5) per-goal and per-rule limits → (6) Decimal rounding → (7) partial-allocation policy. It must hold under concurrent execution; an ordered SQL query alone is not a concurrency guarantee. |
| P49 | Planned **outgoing** AccountTransfers reduce `reservable` capacity; planned **incoming** Transfers never increase current capacity. This is a read-model calculation over the existing canonical planned `account_transfers` records only: a planned Transfer still creates no `AccountTransaction`, no future ledger rows are invented, and existing AccountTransfer semantics are unchanged. A posted Transfer is represented by its ledger rows and is no longer counted as planned. |
| P50 | Unattended `AUTO` may be presented as guaranteed automation only once a **durable periodic dispatcher** exists. The mechanism is not fixed by this contract (a hosting-platform scheduled job, another supported scheduled execution mechanism, or another small durable backend mechanism) and must be technically verified before implementation. Working cadence target ≈ 10 minutes (range 5–15), an operations parameter. Without it, a beta may only promise execution at the next supported user-triggered drain. |
| P51 | v1 live window `N = 7` days. A manually created Income is classified `manual/live` only when its financial date (`received_at`) falls within the seven-day live-entry window; older manual entries are `manual/historical`: valid Income that participates in normal accounting and Financial Overview, but never triggers retrospective `AUTO` allocation. No user override in v1. Provenance remains the primary semantic guard; VF-021 imports are classified by their import provenance, not by timestamps alone. |
| P54 | `CONFIRM` proposals expire after **7 days**. Expiry creates no reservation and no GoalTransaction; an expired proposal can never be confirmed; a repeated action returns the terminal state. Lazy expiry at read, confirmation and dispatch is acceptable. |
| P55 | A valid pending `CONFIRM` proposal creates a **soft capacity hold** that reduces the capacity available to later rule evaluations and so preserves P48. The hold is not part of `reserved_amount`, is not a GoalTransaction, does not change any Account balance, and does not block a real Expense, an AccountTransfer or an explicit manual Goal reservation. Because a manual action may consume the underlying capacity, every confirmation fully revalidates; insufficient capacity rejects the confirmation and cancels the proposal as stale with no hidden partial write. The hold ends when the proposal is executed, rejected, expired, cancelled or superseded. A proposal never counts against its own confirmation. |
| P56 | The Account safety floor is strict for rule-generated allocations and **warning-only** for an explicit manual Goal reservation. The floor warning never overrides P04 capacity, ownership, currency equality, partition non-negativity, Goal/Account lifecycle restrictions or any other hard invariant: a manual reservation can never reserve money that does not exist under the reservable-capacity model. *The principle is unchanged; the floor itself is introduced in VF-020E (P60).* |
| P58 | **`effective_date` rules differ for tracked and linked operations** (approved 2026-10-07; supersedes the earlier PROPOSED wording). *Tracked* (`account_id IS NULL`): exactly the established B3 semantics (P13) - omitted = server `date.today()`, today and any past date accepted, a future date → 422. *Linked* (`account_id IS NOT NULL`), for **both** a linked contribution and a linked withdrawal/release: `client_request_id` is mandatory (422 without it); `effective_date` omitted = server `date.today()`; an explicit `effective_date` must equal server today, otherwise **422** (past and future alike). Idempotency precedence is unchanged (P14, B3): an occupied `client_request_id` is resolved **before** any new-request date or lifecycle check, so an omitted-date retry on a later day replays the original linked transaction with its original `effective_date` (200). |
| P60 | **Safety floor deferred to VF-020E.** VF-020C adds no `Account.floor` or equivalent, no floor field and no floor warning. Manual linked reservation capacity in VF-020C is based only on the base capacity formula (§8.1 `reservable`). P56 stays approved as a principle. |
| P61 | **User-wide advisory lock L0 deferred to VF-020D/E.** VF-020C adds no advisory lock. Correctness uses deterministic row locking: Goal `FOR UPDATE` → Account `FOR UPDATE` → `goal_transactions` insert/read (§14.2). Adding L0 later is additive and must then cover every goal write, manual ones included. **Superseded by P68 (2026-10-13): L0 is introduced in VF-020D and, from that point, applies to every Goal write; it is not scoped to rank-affecting writes only.** |
| P62 | **Account read model (VF-020C):** `current_balance` is unchanged; the additive fields and their exact formulas are in §8.1 and §20.3 (`balance_as_of_today`, `scheduled_outflows`, `planned_transfer_outflows`, `reserved_amount`, `unallocated_amount`, `reservable_amount` (signed), `allocation_status` ∈ {`normal`, `overcommitted`}, `negative_balance`). No `proposal_holds_amount` and no floor fields before VF-020E. A new reservation requires `reservable_amount > 0` and `amount ≤ reservable_amount`; otherwise 409 with no partial write. |
| P63 | **Goal read model (VF-020C):** `current_amount` stays the total Goal balance; additive `tracked_amount`, `linked_amount` and `allocations[]` (§7.2, §20.1). `allocations[]` is the **current non-zero partition summary**, not an audit history; no historical Account ownership is inferred. |
| P64 | **Partition selection and idempotency (VF-020C):** a withdrawal/release always names its partition through `account_id` (omitted/null = tracked; `A` = the linked partition of Account A). No FIFO, no automatic Account selection, no cross-partition withdrawal. `amount` above the selected partition's balance → 409. The canonical idempotency payload gains `account_id`: same key + same payload including `account_id` → 200; same key with a different `account_id`, or a retry that omits `account_id` for a transaction that is linked → 409. Archived Account: no new linked contribution, linked withdrawal/release allowed. Archived Goal: no new contribution of any kind, tracked and linked withdrawals allowed. Completed Goal: unchanged (P11). |
| P65 | **Account lifecycle protection (VF-020C):** deleting an Account, or changing its currency, returns a controlled **409** whenever **any** linked `goal_transactions` row references the Account - historical references count even when the linked net balance is zero. A raw foreign-key `IntegrityError` must never surface as a 500. |
| P66 | **Schema and rollout (VF-020C):** one architecture - nullable `goal_transactions.account_id`, no separate allocations table, no provenance/source column; schema candidate in §19.2; rollout **C1 (schema expand only) → production migration → C2 (backend runtime) → C3 (mobile)** with no later contract migration, because `account_id` intentionally stays nullable (§28). |
| P67 | **Ranked Goals (VF-020D, D01):** all non-archived Goals are ranked: `active` → ranked, `completed` → ranked, `archived` → `priority_rank = NULL`. This matches current product semantics (completed Goals stay current and remain valid targets, P11). The older wording "only active Goals are ranked" is withdrawn. |
| P68 | **L0 is introduced in VF-020D (D02) and covers every Goal write.** Goal create, Goal PATCH (edit and status transition), Goal DELETE, tracked contribution, tracked withdrawal, linked contribution, linked withdrawal/release and the priority reorder all take L0 before any Goal or Account row lock. Account delete and Account currency change do **not** take L0. An occupied-key idempotent replay that performs no new Goal write does not take L0. Exact contract in §14.5. |
| P69 | **L0 key (D02):** `pg_advisory_xact_lock(bigint)`, key = first 8 bytes (big-endian, signed int64) of `SHA-256(b"valor-finis:l0:user:v1:" + user_id.bytes)`. No Python `hash()`. §14.5. |
| P70 | **Rank gaps (D03):** archive and hard delete never compact ranks automatically; gaps are valid. An explicit reorder rewrites the ranked set to `1..n`. |
| P71 | **Backfill (D04):** existing non-archived Goals are ranked per user by `created_at DESC, id ASC` (`row_number()` = `priority_rank`), which preserves the existing newest-first semantics (equal `created_at` values are deterministically ordered by `id ASC`); archived Goals stay NULL. A deterministic initial preference only; it invents no financial history. After priorities exist, `priority_rank` is authoritative. |
| P72 | **Schema and staging (D05, D06):** `priority_rank INTEGER NULL`; `CHECK (priority_rank IS NULL OR priority_rank >= 1)`; `UNIQUE (user_id, priority_rank) DEFERRABLE INITIALLY DEFERRED` (NULLs allowed; no partial index). The lifecycle invariant `(status = 'archived') = (priority_rank IS NULL)` is added only in VF-020D5, after the runtime is deployed and rollout stragglers are normalized. Primary correctness is L0 plus the locked rewrite; the unique constraint is a backstop. |
| P73 | **Reorder API (D07, D08):** `PUT /api/v1/goals/priorities`, body `{"goal_ids": [uuid, ...]}` = the complete ordered set of the user's non-archived Goals. Status codes and the response are in §9. Archived Goals keep `created_at DESC, id ASC`. |
| P74 | **API exposure and canonical order (D09, D13):** `GoalResponse` adds `priority_rank: int \| null`; `GoalCreate` and `GoalUpdate` never accept it. `GET /goals` is priority-aware: non-archived by `priority_rank ASC`, then archived by `created_at DESC, id ASC`. Consumers (including the Dashboard) follow it; no separate creation-date sort is added. Analytics stay keyed by Goal identity. |
| P75 | **Mobile (D10):** a dedicated Priorities screen/mode with ▲ / ▼ and Save, a local draft, no request per arrow press, one PUT on Save, no drag-and-drop dependency. Details in §9. |
| P76 | **Idempotency and boundary (D12):** the reorder needs no `client_request_id` and no idempotency table (a full-state PUT is naturally idempotent). Priority operations never write `GoalTransaction`, `AccountTransaction`, Income, Expense or Transfer rows. VF-020D provides only the ordering and lock foundation for VF-020E. |
| P77 | **Rollout and production gates (D14):** D1 contract, D2 expand migration, production gates, D3 backend runtime, D4 mobile, D5 contract migration, then integration and acceptance (§28). Each production migration (D2 and D5) follows the same ordered sequence: (1) explicit authorization, before any production access; (2) read-only preflight; (3) backup; (4) backup verification; (5) short lock timeout; (6) migration; (7) post-migration verification. |

P34 (reversal after a trigger change) is **superseded by P47**.

---

## 4. Pending and External Decisions

| ID | Topic | Status | Finalized in |
|---|---|---|---|
| P08 | Moving a reservation between Accounts: manual release + reserve; an atomic move is deferred | PROPOSED | — |
| P17 | Attributing an Expense to a Goal | PROPOSED (deferred) | — |
| P23 | Automatic canonical posting of imported transactions | UDR | VF-021 |
| P24–P26 | Review of ambiguous imports; matching manual/receipt records; bank vs ledger balance | PROPOSED | VF-021 |
| P30, P32, P33 | Server-date timezone in v1; `AUTO` blocked on incomplete data; in-app notification defaults | PROPOSED | VF-020E |
| P38 | Credit-card / liability accounts outside VF-020 | PROPOSED / EXT research | VF-021 |
| P41, P43 | User timezone (deferred); in-app channel | PROPOSED | VF-020E |
| P53 (external part) | Any later legal / provider retention requirement for `financial_events` (the VF-020E technical behavior is APPROVED, §12.9) | EXT | VF-021 / legal review |
| P59 | Timing for making `client_request_id` mandatory for all clients | PROPOSED | after VF-020F |
| P20, P21, P22, P27, P39 | Access model, provider/region, wallets, retention after disconnect, card FX | **EXT** | VF-021 |
| P50 mechanism | Verification of the periodic dispatcher mechanism (the requirement is APPROVED and the scheduled-process boundary is fixed by P87). **P50 TECHNICAL VERIFICATION STILL REQUIRED** | technical verification | VF-020E |

**Approved by VF-020E1 (2026-10-16), removed from this list:** P28, P31, P37, P42, P52, P53 (technical behavior), P57 (§27). New decisions P78–P88 are in §27.

---

## 5. Existing Architecture (EST)

- Modular monolith; FastAPI with Router → Service → Repository → SQLAlchemy →
  PostgreSQL 16; Alembic; Supabase Auth (JWT); backend hosted on Render.
- Mobile: Expo SDK 57, Expo Router, TypeScript, TanStack Query. Supabase is used
  for auth only; all finance CRUD goes through FastAPI. The device workflow is
  Expo Go over LAN.
- Supabase Data API privileges are revoked on the application tables
  (migrations `edcfdf3f7114`, `1edb74dc96d8`).
- **There is no background mechanism**: no scheduler, worker, queue,
  `BackgroundTasks` or advisory locks exist in the code at the baseline.
- `income_service.create_income` supports `commit=False`: Income, its Account
  projection and a new outbox event can commit together. External FX
  resolution happens **before** any row lock.

---

## 6. Canonical Financial Invariants

### 6.1 Established

| ID | Invariant | Where |
|---|---|---|
| INV-01 | `Decimal` / `NUMERIC(12,2)`; money reaches mobile as decimal strings. | models, schemas |
| INV-02 | `user_id` comes only from authentication; repositories are user-scoped; the Account ledger uses composite `(…, user_id)` foreign keys. | `account_transaction_models.py` |
| INV-03 | Income, Expense and AccountTransfer are canonical; `account_transactions` holds their projections. | `docs/architecture.md` §5 |
| INV-04 | `current_balance` = SUM of all of the Account's ledger rows, with no date filter; it may be negative; there is no insufficient-funds check. Future-dated rows can come from Income/Expense in the base currency, adjustments and opening balances; Transfer projections are only ever dated ≤ today. | `account_transaction_repository.calculate_ledger_balance` |
| INV-05 | Every write to the Account ledger first locks the Account row: Income/Expense create/update/delete, Receipt confirmation, adjustments, Transfer create/post/delete. Order: canonical row → Accounts in ascending UUID. | income, expenses, accounts services |
| INV-06 | Goal balance ≥ 0; overfunding allowed; history append-only; status manual; currency immutable once history exists; a Goal with history cannot be deleted. | `goal_service.py` |
| INV-07 | Goal writes lock the Goal row first. | `goal_repository.get_goal_by_id_for_update` |
| INV-08 | Transfers: same currency, idempotent, neither Income nor Expense, no interaction with Goals. A planned Transfer has **no** ledger rows (`effective_date IS NULL`). | `account_transfer_models.py`, `docs/modules/account-transfers.md` |
| INV-09 | Financial Overview reads only canonical Income/Expense `base_amount`; unresolved FX records are counted separately. | `docs/modules/financial-overview.md` |
| INV-10 | Historical `base_amount` snapshots are never revalued. | FX module |
| INV-11 | Budgets are the authority on spending limits (`category_id` nullable, `limit_amount`, `currency`, `period` weekly/monthly/yearly, `start_date`/`end_date`, versions); status via `GET /api/v1/analytics/budget-status`, `risk_status` ∈ healthy/watch/at_risk/exceeded. | `budgets_models.py`, `budget_metrics.py` |
| INV-12 | "Today" = server `date.today()` (known limitation D13); there is no per-user timezone. | analytics, `financial_settings` |
| INV-13 | Income: full CRUD; `amount`, `currency`, `received_at`, `source` ∈ {salary, freelance, refund, gift, other}, `description`, FX snapshot, `created_at`, `updated_at`; **no lifecycle status**. | `income_models.py` |
| INV-14 | Archived Account: no new direct activity and no attach/move-in; detach/move-out allowed. | `income_service.py`, `expenses_service.py` |
| INV-15 | Destructive tests run only against a `*_test` database. | `tests/database_safety.py` |

### 6.2 Known gaps closed in VF-020B

| ID | Gap |
|---|---|
| G1 | Goal currency validation accepts non-alphabetic codes such as `"12$"`. |
| G2 | `goals.status` has no database CHECK. |
| G3 | The database does not guarantee that a goal transaction's owner equals the goal's owner. |
| G4 | Archived and completed Goals accept contributions (resolved by P10/P11). |
| G5 | Goal transactions have no idempotency (P14). |
| G6 | `goal_repository.get_goals(user_id=None)` returns every user's goals. |

### 6.3 Contract invariants for VF-020/021

| ID | Invariant |
|---|---|
| FIN-001 | No invented money: Goals, rules, priorities, holds and reservations never create Account money. |
| FIN-002 | No double counting: one economic event = at most one canonical record; Goal balances are never added to Account totals, net worth or Financial Overview. |
| FIN-003 | Canonical records stay authoritative; imports are evidence. |
| FIN-004 | A reservation is not a transfer, payment or withdrawal. |
| FIN-005 | Historical `base_amount` stays authoritative. |
| FIN-006 | Decimal everywhere; money is sent to mobile as strings. |
| FIN-007 | Ownership on every read and write; a provider identifier is never authorization. |
| FIN-008 | Related financial changes are atomic. |
| FIN-009 | Repeated requests, events and executions never duplicate a financial effect. |
| FIN-010 | Data completeness is visible; incomplete required state never feeds `AUTO`. |
| FIN-011 | GoalTransaction history is append-only; legacy history is never rewritten. |
| FIN-012 | Financial Overview semantics do not change. |

---

## 7. Goal Financial Semantics

### 7.1 Move, reserve, track

- **Move** money between Accounts = an AccountTransfer: outside VF-020 (P16, INV-08).
- **Reserve** money that stays in an Account = a linked partition (P02).
- **Track** progress without any claim about Accounts = the tracked partition, today's behavior (P02, P12).

### 7.2 Partitions (P02, P03, P07)

```
tracked(G)    = Σ opening_balance(G) + Σ contribution(G, account NULL) − Σ withdrawal(G, account NULL)
linked(G, A)  = Σ contribution(G, A) − Σ withdrawal(G, A)
total(G)      = tracked(G) + Σ_A linked(G, A)          -- identical to today's Goal balance formula
reserved(A)   = Σ_G linked(G, A)                       -- across all of the user's Goals, archived included
```

After every write: `tracked(G) ≥ 0` and `linked(G, A) ≥ 0` for every Account A.
No `AccountTransaction` is created for a reservation (FIN-004). No Goal
allocation changes Financial Overview (FIN-012).

**API representation (APPROVED P63).** `current_amount` = `total(G)` and keeps
its meaning. Additive fields: `tracked_amount = tracked(G)`;
`linked_amount = Σ_A linked(G, A)`; `current_amount = tracked_amount +
linked_amount`; `allocations[] = [{ "account_id", "amount" }]` for every
Account whose `linked(G, A) ≠ 0`. `allocations[]` is a **current non-zero
partition summary, not an audit history**: it lists no past releases, no dates
and no zero partitions, and it infers no historical Account ownership (legacy
rows stay tracked, P12). The audit trail remains the GoalTransaction history,
which gains `account_id` per row. `tracked_amount`, `linked_amount` and
`allocations[]` are computed in one grouped query per request (no per-Goal
queries).

**Partition selection (APPROVED P64).** A withdrawal or release selects its
partition **explicitly** through `account_id`: omitted/null = the tracked
partition, `A` = the linked partition of Account A. There is no FIFO, no
automatic Account selection and no cross-partition withdrawal. An amount above
the selected partition's balance → 409 even when the Goal's total would cover
it; the error identifies the partition.

### 7.3 GoalTransaction fields

| Field | Status | Notes |
|---|---|---|
| `goal_id`, `user_id`, `type`, `amount`, `description`, `created_at` | EST | unchanged; `amount > 0`; `type` CHECK unchanged |
| `account_id` (NULL = tracked) | **APPROVED** (P02/P03/P66) - column added by VF-020C1, mapped and used from VF-020C2 | `UUID NULL`, no default, no backfill; composite FK `(account_id, user_id, currency)` → `accounts(id, user_id, currency)` ON DELETE RESTRICT; the target unique constraint `uq_accounts_id_user_id_currency` already exists |
| `currency` | **EST (VF-020B3/B4)** | `NOT NULL`; copy of `goals.currency`; FK `(goal_id, user_id, currency)` → `goals(id, user_id, currency)`; Goal currency is immutable once history exists |
| `effective_date` | **EST (P13) + APPROVED (P58)** | NULL for legacy rows. Tracked: `≤ today` checked by the service. Linked (contribution and withdrawal/release): omitted = server today; explicit must equal server today (P58) |
| `client_request_id` | **EST (P14)** | `UNIQUE(user_id, client_request_id)`; mandatory for linked rows (P58) |
| `rule_execution_id` | PROPOSED (VF-020E) | composite FK `(rule_execution_id, user_id)` → `rule_executions(id, user_id)`; not part of VF-020C |
| `CHECK (type <> 'opening_balance' OR account_id IS NULL)` | **APPROVED** (P66) | opening balances always stay tracked |
| `CHECK (account_id IS NULL OR client_request_id IS NOT NULL)` | **APPROVED** (P66) | database-level form of the mandatory key for linked rows; legacy rows are unaffected |
| `CHECK (account_id IS NULL OR effective_date IS NOT NULL)` | **APPROVED** (P66) | linked rows always carry a business date |

### 7.4 Compatibility

| Consumer / case | Behavior |
|---|---|
| Existing `POST /api/v1/goals/{id}/transactions` without `account_id` | Tracked row with the established B3 semantics: `effective_date` omitted = today, past/today accepted, future → 422; optional `client_request_id` (§20.2). |
| Withdrawal without `account_id` | Validated against `tracked(G)` only (P64); for legacy goals `tracked = total`, so nothing changes. For a Goal that also has linked partitions it can no longer draw on them: 409 naming the partition. |
| Linked operation (`account_id` set), contribution or withdrawal/release | `client_request_id` mandatory (422 otherwise); `effective_date` omitted or equal to today (422 otherwise) (P58). |
| Archived Goal | Contributions (tracked and linked) → 409 (P10); implemented for tracked contributions in VF-020B1 with regression tests; VF-020C extends it to linked contributions. Withdrawals/releases stay allowed. |
| Completed Goal | Unchanged (P11). |
| Goal currency change | Unchanged rule (409 once history exists); the composite FK is the last line of defense. |
| `GET /api/v1/analytics/goal-progress` | `current_amount` = total; meaning unchanged; only additive fields. |
| API responses | Additive fields only (`account_id`, `effective_date`, `rule_execution_id`, partition breakdowns). Tests comparing complete dicts may need updating without any behavior change. |
| Mobile types | Additive; existing clients ignore new fields. |

Historical rows are never rewritten. The only data operation in scope is the
deterministic `currency` copy (P19), which requires its own migration approval.

### 7.5 Example

Account A balance as of today 2,000.00 EUR. Goal G: 300.00 tracked + 500.00 linked to A.
A reserved 500.00 · A unallocated 1,500.00 · G total 800.00 · user assets 2,000.00 (**not** 2,800.00).

---

## 8. Account Reservations and As-Of Balances

### 8.1 Formulas (read model; nothing is stored)

```
D                          = as_of_date: server date.today(), resolved once per request or transaction (INV-12)
current_balance(A)         = Σ all ledger rows of A                    -- EST, unchanged ("Recorded balance")
balance_as_of(A, D)        = Σ ledger rows of A with transaction_date ≤ D   ("Balance as of today")
scheduled_outflows(A, D)   = Σ debit ledger rows of A with transaction_date > D
planned_transfer_out(A)    = Σ amount of account_transfers with status = 'planned' AND source_account_id = A
reserved(A)                = §7.2
unallocated(A)             = balance_as_of(A, D) − reserved(A)
reservable(A)              = unallocated(A) − scheduled_outflows(A, D) − planned_transfer_out(A)
floor(A)                   = floor_amount of the ENABLED MINIMUM_UNALLOCATED_FLOOR rule of A, else 0   (§10.6, P78)
active_holds(A)            = Σ rule_execution_items.planned_amount WHERE item.account_id = A
                             AND execution.status = 'awaiting_confirmation' AND execution.expires_at > now
                             -- an expired proposal is excluded even before lazy state normalization; no holds table
rule_capacity(A)           = reservable(A) − floor(A) − active_holds(A)    -- signed
                             -- AUTO executions and creation of NEW CONFIRM proposals
prior_holds(A, X)          = Σ active holds on A whose proposal has hold_sequence < X.hold_sequence (§11.3, P80);
                             X's own hold and later holds are never included
confirm_capacity(A, X)     = reservable(A) − floor(A) − prior_holds(A, X)
                             -- confirmation of an existing proposal X
```

- `balance_as_of` is not a competing balance: it is the same ledger read with a
  date boundary. `current_balance` keeps its name, meaning and API position.
- **No double subtraction:** future-dated debit ledger rows (`scheduled_outflows`)
  and planned Transfers (no ledger rows) are disjoint sets. Posting a planned
  Transfer requires `effective_date ≤ today`, so its projections land in
  `balance_as_of` and it leaves `planned_transfer_out` in the same transaction.
- Planned **incoming** Transfers and future-dated credits are never added.
- `reservable` is the capacity before rule-specific constraints. Holds reduce
  only `rule_capacity` and `confirm_capacity`; they are not part of `reserved`,
  `unallocated` or `reservable` (P55).
- A proposal never counts its own hold against its confirmation:
  `confirm_capacity` excludes it by construction (§11.3).
- All amounts are Decimal in the Account currency; a Transfer, a linked
  reservation and the Account always share one currency (INV-08, P06).

**VF-020C scope of the formulas (APPROVED P60, P62).** VF-020C implements
`current_balance`, `balance_as_of`, `scheduled_outflows`, `planned_transfer_out`,
`reserved`, `unallocated` and `reservable`. `floor`, `active_holds`,
`rule_capacity` and `confirm_capacity` belong to VF-020E and are not exposed or
computed before it (staging: `minimum_unallocated_floor` in E5, `active_rule_holds` and
`rule_capacity` in E7; `confirm_capacity` only in the proposal read model, never on
`AccountResponse`, §20.3, P86). Exact definitions as returned by `GET /api/v1/accounts`
(D = server `date.today()`, resolved once per request; every amount is a
Decimal string in the Account currency):

| API field | Exact definition |
|---|---|
| `current_balance` | unchanged: signed sum of **all** ledger rows of the Account (no date filter) |
| `balance_as_of_today` | signed sum (credit +, debit −) of the Account's `AccountTransaction` rows with `transaction_date ≤ D` |
| `scheduled_outflows` | sum of the Account's **debit** `AccountTransaction` amounts with `transaction_date > D` (a positive number) |
| `planned_transfer_outflows` | sum of `amount` of `AccountTransfer` rows with `status = 'planned'` and `source_account_id` = this Account, regardless of `planned_date`; planned incoming Transfers are ignored; posted Transfers are already in the ledger and never counted here |
| `reserved_amount` | Σ linked contributions − Σ linked withdrawals (`goal_transactions` with `account_id` = this Account) across **all** of the user's Goals, archived and completed included |
| `unallocated_amount` | `balance_as_of_today − reserved_amount` |
| `reservable_amount` | `unallocated_amount − scheduled_outflows − planned_transfer_outflows`; **signed, may be negative** |
| `allocation_status` | `"overcommitted"` when `reserved_amount > 0` **and** `unallocated_amount < 0`, otherwise `"normal"` |
| `negative_balance` | `balance_as_of_today < 0` |

**New reservation rule (P04, P62):** a new linked contribution of `amount`
requires `reservable_amount > 0` **and** `amount ≤ reservable_amount`; otherwise
409 and nothing is written. Releases and withdrawals do not check capacity.
Reservations never block an Expense, a Transfer or an adjustment (P05): after
such an operation `reserved_amount` is unchanged and the Account may become
`overcommitted`; the Goal history is never rewritten. There is no
`proposal_holds_amount` and no floor field in VF-020C.

### 8.2 Clarifications

| # | Topic | Contract |
|---|---|---|
| 1 | Date boundary | A row is present if `transaction_date ≤ D`; D is fixed once per request or dispatcher transaction. |
| 2 | Future credits | Excluded from `balance_as_of` and from every capacity figure; they never create capacity (P36). |
| 3 | Future debits | Excluded from `balance_as_of`, subtracted through `scheduled_outflows` (P36). |
| 4 | Opening balance | Dated by `opening_balance_date` (default: day of creation). A future-dated positive opening balance is a future credit; a negative one is a scheduled outflow. |
| 5 | Adjustments | By `transaction_date` and `direction`, like any other row. |
| 6 | Future-dated Income/Expense | Through their projections (`received_at` / `expense_date`), like any other row. |
| 7 | Planned Transfers | No ledger rows exist and none are invented. Planned outgoing Transfers are subtracted through `planned_transfer_out` regardless of `planned_date` (a past `planned_date` can still be unposted because posting is manual); planned incoming Transfers are ignored (P49). |
| 8 | Negative balance | Allowed (INV-04). `reservable ≤ 0` → new reservations get 409; releases are always allowed. |
| 9 | Archived Account | All figures are computed and shown; new linked contributions → 409 (P09); rules are `blocked`. |
| 10 | Overcommitted | `allocation_status = overcommitted` ⇔ `reserved > 0 ∧ unallocated < 0` (VF-020C: values `normal` / `overcommitted` only). `negative_balance` is a separate flag. The `scheduled_shortfall` warning (`reserved > 0 ∧ unallocated ≥ 0 ∧ reservable < 0`, PROPOSED term) is **not** part of VF-020C; `reservable_amount` is returned signed, which already shows it. |
| 11 | Manual vs rule allocations | Manual reservations are limited by `reservable` (P04); in VF-020C there is no floor and no warning (P60), and holds do not exist yet. From VF-020E: the floor only warns for manual reservations (P56) and holds do not apply (P55); AUTO executions and the creation of new CONFIRM proposals are limited by `rule_capacity`; confirming an existing proposal X is limited by `confirm_capacity(A, X)`, which excludes X's own hold (§11.3); the floor is strict in both rule cases. |
| 12 | Safety floor | `MINIMUM_UNALLOCATED_FLOOR` rule per Account (§10.6, P78) - **deferred to VF-020E (P60)**; VF-020C stores no floor, and the floor is never an Account column. |
| 13 | Date rollover | Figures change without writes; deferred events become due (§12); overcommitment may appear or disappear; history is never rewritten; Financial Overview rollover is unaffected. |
| 14 | Timezone | Server date; device and server may disagree near midnight (D13); a user timezone is deferred (P41). |

Bank-reported balances (VF-021) are a separate observation and never enter these formulas (P26).

### 8.3 Account lifecycle with reservations

- **Archive:** allowed (P09).
- **Delete (APPROVED P65):** the pre-check returns a controlled 409
  `AccountReferencedByGoalAllocation` when **any** linked `goal_transactions`
  row references the Account - the **historical** reference is enough, even
  when the linked net balance is now zero (append-only history is never removed,
  and the foreign key is RESTRICT). `AccountReferencedByRule` is added by
  VF-020E. FK RESTRICT is the last line of defense and must never become a 500.
  The pre-check is mandatory: deleting the only linked Income can leave an
  Account with no ledger rows but live reservations, where today's history check
  would pass and the FK would surface as a 500.
- **Currency change (APPROVED P65):** the pre-check returns 409 whenever linked
  Goal history references the Account (rules are added by VF-020E); the
  composite FK is the last line of defense (VF-018C pattern). Because the Goal
  currency is itself immutable once history exists, a linked row can never be
  rewritten to another currency.
- Both pre-checks run under the Account row lock and only **read**
  `goal_transactions` (§14.2).

---

## 9. Goal Priorities (APPROVED, VF-020D; P67–P77; principles follow APPROVED P48)

Status: contract finalized in VF-020D1; **implemented and complete** (D2 migration `4d2f7b91a6c3`, D3 backend PR #81, D4 mobile PR #82, D5 lifecycle migration `7c1e5a9b3d28`, PR #83; production at `7c1e5a9b3d28`).

**Ranked set (P67).** All non-archived Goals are ranked: `active` and
`completed` have a non-NULL `priority_rank`, `archived` has
`priority_rank = NULL`. Completed Goals remain current, visible and valid
targets (P11, E9).

**Data (P72).** `priority_rank INTEGER NULL`, 1 = highest;
`CHECK (priority_rank IS NULL OR priority_rank >= 1)`;
`UNIQUE (user_id, priority_rank) DEFERRABLE INITIALLY DEFERRED` as a backstop
(NULL ranks are allowed; no partial index; the deferral lets a reorder rewrite
swap ranks inside one transaction). Primary correctness is L0 (§14.5) plus the
locked rewrite. The lifecycle invariant
`(status = 'archived') = (priority_rank IS NULL)` is added only in VF-020D5.

**Order (P74).** Canonical Goal order: non-archived Goals by
`priority_rank ASC`; then archived Goals by `created_at DESC, id ASC`. Priority
does not reorder archived Goals. A non-archived Goal that still has a NULL rank
(created between the D2 migration and the D3 deployment) sorts after the ranked
ones by `created_at ASC, id ASC` until normalized.

**Backfill (P71).** Per user over non-archived Goals:
`row_number() OVER (PARTITION BY user_id ORDER BY created_at DESC, id ASC)` =
`priority_rank`. The backfill preserves the existing newest-first semantics; equal
`created_at` values are deterministically ordered by `id ASC`.
Archived Goals stay NULL. Completed Goals are ranked. This invents no financial
history; it is only a deterministic initial preference.

**Lifecycle (P70).**

| Event | Rank |
|---|---|
| create, non-archived | appended last: `COALESCE(MAX(priority_rank), 0) + 1` for the user, under L0 |
| create, archived | NULL |
| active ↔ completed | unchanged |
| active/completed → archived | NULL; remaining ranks are **not** compacted |
| archived → active/completed | appended last (same formula, under L0) |
| non-status edit | unchanged |
| hard delete | row removed; a gap remains (no compaction) |

Gaps are valid (`1,2,3,4` → archive rank 2 → `1,3,4`). A later explicit
reorder rewrites the ranked set to `1..n`. The unrestricted valid-status PATCH
behavior is otherwise unchanged.

**Reorder (P73).** `PUT /api/v1/goals/priorities`

```json
{ "goal_ids": ["<uuid>", "<uuid>"] }
```

`goal_ids` is the **complete** ordered set of the user's non-archived Goals;
`extra="forbid"`.

| Case | Result |
|---|---|
| malformed UUID, duplicate ids | 422 |
| unknown Goal, or a Goal owned by another user | 404 "Goal not found." (indistinguishable) |
| an archived Goal supplied | 409 |
| a ranked Goal missing from the list (stale set) | 409, reload and retry |
| an extra or ineligible Goal after ownership/existence passed | 409 |
| empty list | 200 only when the user has zero ranked Goals; otherwise 409 |
| the exact current order again | 200 (idempotent) |
| one Goal | 200 |

Under L0 the server re-reads and revalidates the current ranked set after
acquiring the lock (and the Goal rows, ascending id); if the set differs from
the client's list the answer is 409 reload-and-retry. On success ranks are
rewritten `1..n` in the given order.

**Response.** 200 with the complete canonical Goal list in the normal
`GoalResponse` shape, **including archived Goals**, ordered as above, so a
client can replace `["goals", userId]` from one authoritative payload. There is
no 204/refetch design.

**Exposure (P74).** `GoalResponse` adds `priority_rank: int | null`.
`GoalCreate` and `GoalUpdate` do **not** accept `priority_rank`; the only way a
user changes it is the PUT. Lifecycle operations control it automatically.

**Idempotency (P76).** The PUT is a full-state replacement and is naturally
idempotent: no `client_request_id`, no idempotency table. It never writes
`GoalTransaction`, `AccountTransaction`, Income, Expense or Transfer rows.

**Mobile (P75).** A dedicated Priorities screen (or mode):

- shows only non-archived Goals, active and completed;
- ▲ move up and ▼ move down on a local draft order (no request per press;
  boundary buttons are disabled; no drag-and-drop dependency);
- one PUT on Save; Save is disabled while the request is pending and while the
  draft equals the server order;
- on success the Goals cache is replaced from the response;
- on a stale-set 409: refetch Goals, reset the draft and show a controlled
  reload/retry message;
- every button has a meaningful accessibility label.

Cache: the authoritative response replaces `["goals", userId]`. Accounts, Goal
transactions, Financial Overview and Goal progress analytics are not
invalidated (analytics are joined by Goal identity and never derive meaning
from list order). No VF-020E query keys exist yet and none are invented here.

**Position relative to rules (P48).** Rule order precedes Goal priority
(levels 3 → 4); Goal priority orders the targets **inside** one rule. A
priority change affects only future evaluations; a deadline affects only
estimates. VF-020D provides only the rank, the canonical order, lifecycle rank
handling, the reorder endpoint, L0 for every Goal write and the mobile
priorities UX - none of the VF-020E rules machinery.

---

## 10. Rules Engine

### 10.1 v1 scope

| Type | Kind | Mode | v1 |
|---|---|---|---|
| `INCOME_ALLOCATION` | internal reservation | AUTO / CONFIRM (P01) | yes |
| `MINIMUM_UNALLOCATED_FLOOR` | per-Account constraint (a `financial_rules` row, P78) + alert; never executes | — | yes |
| `OVERCOMMITMENT_ALERT` | alert; never executes | — | yes |
| `BUDGET_ALERT` | alert observing a Budget; never executes | — | yes |
| `GOAL_DEADLINE_ALERT` | alert | — | deferred / optional; **not** enabled by an unused enum value (P84) |
| Scheduled (calendar) allocation | reservation | AUTO / CONFIRM | **no**: requires a user timezone (P41) and a scheduler |
| Proportional / residual / deadline-weighted distribution | — | — | deferred |

**Rule types supported by `financial_rules` in v1 (P84):** `INCOME_ALLOCATION`,
`MINIMUM_UNALLOCATED_FLOOR`, `OVERCOMMITMENT_ALERT`, `BUDGET_ALERT`. Only
`INCOME_ALLOCATION` creates `rule_executions`, `rule_execution_items` and
GoalTransactions. The other three types never create executions, proposals or
GoalTransactions, have no `execution_mode`, no `execution_order` and no Goal targets.

### 10.2 Definition

Typed: a Pydantic discriminated union by `rule_type`. **No scripts, no
expressions, no user-supplied code.**

`INCOME_ALLOCATION` fields:

| Field | Meaning |
|---|---|
| `name`, `status` (draft/enabled/paused/disabled), `execution_mode`, `execution_order`, `version` | |
| `active_since` | timestamptz; start of the current enabled period, reset on every enable |
| `effective_from` | date; defaults to the activation date |
| `source_account_id` | exactly one Account (APPROVED P31); ownership FK `(source_account_id, user_id)` → `accounts(id, user_id)` ON DELETE RESTRICT; **no currency is stored on the rule** |
| `income_sources` | subset of {salary, freelance, gift, other, refund}; `refund` excluded by default (P35) |
| `policy` | `FIXED_PER_GOAL` \| `PERCENT_OF_INCOME_WATERFALL` |
| `percent` | 0 < p ≤ 100, two decimals |
| targets | `(goal_id, amount_or_cap, position)`; every target Goal's currency equals the source Account currency. `position` is configuration / UI order only and is **never** the financial execution priority: allocation always follows the current `Goal.priority_rank` inside the rule (P48, §9) |
| `cap_at_target` | default true |
| `allow_partial` | default false (P29) |

Rule **validity** (source Account active, targets active, currencies equal) is
derived at read and evaluation time, not stored. Currency equality
`Income = source Account = every target Goal` is validated at create / edit /
enable and again at evaluation; because no currency is stored on the rule, a
mismatch found at execution is a business result `blocked (currency_mismatch)`,
never a technical retry (APPROVED P31, P37).

**Order and invalid rules (APPROVED P28, P37).** Rules are evaluated in
`execution_order ASC, created_at ASC, id ASC`. Duplicate `execution_order` values
and gaps are allowed; there is **no** `UNIQUE (user_id, execution_order)`. A new
`INCOME_ALLOCATION` rule without an explicit order is appended at
`COALESCE(MAX(execution_order), 0) + 1` under L0. An enabled allocation rule whose
referenced domain state is currently invalid creates a terminal `blocked`
execution with a stable `reason_code` (`source_account_archived`,
`target_goal_archived`, `currency_mismatch`); the rule is **never** auto-paused or
auto-disabled and stays visible as enabled-but-invalid until the user fixes it.
`draft`, `paused` and `disabled` rules are not evaluated and create no `blocked`
execution merely because they are inactive. A broken ownership FK or impossible
reference is a data-integrity incident, not a `blocked` result.

### 10.3 Versions and status machine (APPROVED P88)

A material edit increments `version`; executions store the version and a
parameter snapshot. An edit cancels open proposals (`cancelled: superseded`,
which ends their holds) and does **not** reset `active_since`, so it causes no
re-execution of historical Income.

**Material fields:** `execution_mode`, `source_account_id`, `income_sources`,
`policy`, `percent`, `cap_at_target`, `allow_partial`, the target set, a target's
`amount_or_cap`, `effective_from`, `floor_amount`, and the alert subject
(Account or Budget) where changing it changes financial or alert meaning.
**Non-material:** `name`, `description`, `execution_order`. A change of
`execution_order` increments no version, cancels no proposal, and affects future
evaluations only; existing proposals keep their frozen `hold_sequence` (P80).
Status transitions are state operations (`enable`, `pause`, `disable`), not
ordinary PATCH edits.

**Statuses:** `draft`, `enabled`, `paused`, `disabled`. A rule is created as `draft`.

| From | Allowed |
|---|---|
| `draft` | edit, preview, enable, delete (if deletable) |
| `enabled` | edit, pause, disable |
| `paused` | edit, enable, disable |
| `disabled` | edit, enable, delete (if deletable) |

Every transition **into** `enabled` sets `active_since = now()` (so pause → enable
and disable → enable reset it, and Income from a paused or disabled period never
becomes eligible later, E5). `effective_from` defaults to the server date of the
first activation when absent, does not move on later enables, and changes only by
an explicit material edit. `AUTO` requires a preview before enable (a UX rule: the
preview is financially read-only and the backend adds no hidden "previewed" column);
enable re-runs the structural and current validation before changing status.
`CONFIRM` does not require a preview. Pausing or disabling a rule cancels its
open proposals (`cancelled (rule_inactive)`).

### 10.4 Policies

- `FIXED_PER_GOAL`: fixed amounts per target.
- `PERCENT_OF_INCOME_WATERFALL`: `total = ROUND_DOWN(Income.amount × percent / 100, 0.01)`
  (P44, P45), filled in Goal priority order; each target is limited by
  `min(rule cap, max(target_amount − total(G), 0) if cap_at_target)`.
- Target configuration uses one nullable `amount_or_cap NUMERIC(12,2)` per target:
  required fixed amount for `FIXED_PER_GOAL`, optional per-target cap for the
  percentage policy. The allocation order is always the current
  `Goal.priority_rank` (never the target `position`). Only positive,
  cent-quantized amounts are written; with `allow_partial = false` a plan that
  capacity cannot cover is `skipped (insufficient_capacity)` and writes nothing;
  with `allow_partial = true` the amounts are allocated deterministically in Goal
  priority order until capacity is exhausted. No floats anywhere.
- Percentage basis is `Income.amount` in the Account/Goal currency, never
  `base_amount` (P44).

### 10.5 Precedence (APPROVED P48), applied inside one coordinated transaction (§14)

1. Ownership and hard invariants (E1–E10, active statuses, currency, idempotency).
2. `rule_capacity` of the source Account (reservable − floor − active holds)
   for AUTO executions and new proposals; a later confirmation uses
   `confirm_capacity` (§8.1, §11.3).
3. Rule order: `execution_order`, `created_at`, `id` (P28).
4. Goal priority inside the rule (§9).
5. Caps: per target → target remainder → rule total.
6. Rounding: `ROUND_DOWN` 0.01; remainder unallocated (P45).
7. Partial policy (P29).

### 10.6 Safety floor (APPROVED P56, P60, P78, P79)

`MINIMUM_UNALLOCATED_FLOOR(A, amount)` is strict for every rule-generated
allocation on A (AUTO executions and the creation and confirmation of CONFIRM
proposals): `rule_capacity` and `confirm_capacity` subtract it (§8.1). An
explicit manual reservation below the floor is allowed with a warning, but only
within `reservable` and all other hard invariants.

**Storage (APPROVED P78).** The floor is **not** an Account column (an
`accounts.minimum_unallocated_floor` column is explicitly **REJECTED**). It is a
`financial_rules` row with `rule_type = 'MINIMUM_UNALLOCATED_FLOOR'`:

- exactly one such rule per `(user_id, source_account_id)`, enforced by a partial
  `UNIQUE` index; `floor_amount NUMERIC(12,2) CHECK (floor_amount >= 0)`;
- standard rule identity, status and `version` metadata; ownership FK
  `(source_account_id, user_id)` → `accounts(id, user_id)` RESTRICT;
- **no** `execution_mode`, **no** `execution_order`, **no** Goal targets, never an
  AUTO execution or CONFIRM proposal, never a `rule_executions` row or a
  GoalTransaction;
- only status `enabled` contributes `floor_amount`; `draft`, `paused` and
  `disabled` give `floor(A) = 0`;
- changing `floor_amount` or the Account is a material edit (version bump); every
  floor write runs under L0;
- archiving the Account is allowed and keeps the configured floor stored; the
  archived Account still exposes its normal read-model values, allocation rules
  using it are `blocked (source_account_archived)`, and new manual linked
  contributions stay forbidden by P09;
- the floor rule may be the subject of `rule_alerts` (§17).

**Manual floor warning (APPROVED P79).** The hard check is unchanged (P04):
`reservable <= 0` or `amount > reservable` → 409. A contribution that fits is
allowed even if it crosses the floor. With
`projected_reservable = reservable_amount − amount`, a warning is emitted **only**
when `projected_reservable < minimum_unallocated_floor`. Active holds do **not**
take part in this condition: a manual operation never receives a "floor
breached" warning merely because soft CONFIRM holds reduce `rule_capacity`.

The `POST /api/v1/goals/{id}/transactions` response gains an additive field.
**E5 shape (exact):** an empty list, or one object with exactly these keys; E5 does
**not** expose `projected_rule_capacity`, because E5 must not query
`rule_executions`, `rule_execution_items` or active holds (they do not exist until
E6 / E7):

```
"warnings": []
"warnings": [{"code": "minimum_unallocated_floor",
              "minimum_unallocated_floor": "1000.00",
              "projected_reservable_amount": "700.00"}]
```

`projected_reservable_amount = reservable_amount − contribution amount`, and the
warning is activated **only** by `projected_reservable_amount < minimum_unallocated_floor`.

**E7 additive field.** Once the E6 schema is in production and the E7 runtime
computes holds, the same warning object may gain an advisory
`projected_rule_capacity = projected_reservable_amount − minimum_unallocated_floor − active_rule_holds`
(the §8.1 `rule_capacity` formula applied to the projected state; it can be
negative, for example 700.00 − 1000.00 − 0.00 = −300.00). This is additive API
evolution. The warning is **still** activated only by
`projected_reservable_amount < minimum_unallocated_floor`, never by
`projected_rule_capacity < 0`; soft holds alone never cause the manual warning.
The warning is advisory, **not
persisted**, not part of the idempotency payload, never creates a money row and
never blocks the reservation. The historical `GET` GoalTransaction schema is not
changed; the warning is carried by an additive POST response model (subtype).
On an occupied-key replay the original stored GoalTransaction is returned and
`warnings` is **recomputed from the current** Account and floor state, so the
financial effect of the replay is identical even when the warning content differs
(in E5 it has the E5 shape; from E7 it may also carry `projected_rule_capacity`).
For a replay of a stored linked contribution, which is already part of the Account's reserved amount, the projected reservable amount is the Account's **current** `reservable_amount`; a tracked transaction or a withdrawal / release always has an empty list (VF-020E5 implementation).

### 10.7 Examples (each names its policy)

Setup for A–D: today 2026-10-10; CHK (EUR) opening 2,000.00 dated 2026-10-01,
500.00 already reserved for G1; G1 rank 1 (target 3,000), G2 rank 2 (target
5,000), G3 rank 3 (target 1,000); no future rows, no planned Transfers, no
holds. Rule R: `PERCENT_OF_INCOME_WATERFALL` 20 %, source CHK, sources
{salary}, caps G1 300 / G2 200 / G3 none, `cap_at_target`,
`allow_partial = false`, floor(CHK) = 1,000. A salary of 3,000.00 is recorded
with `received_at` = today, linked to CHK.

| Example | Calculation | Result |
|---|---|---|
| A | total 600; balance as of today 5,000, reserved 500, unallocated 4,500; rule_capacity 3,500 | G1 300 · G2 200 · G3 100; reserved 1,100; unallocated 3,900 |
| B | floor 4,200 → rule_capacity 300 < 600 | `skipped (insufficient_capacity)`; with `allow_partial`: G1 300, `executed_partial` |
| C | 3,333.33 × 7 % = 233.3331 | G1 233.33; 0.0031 unallocated |
| D | R (order 1) as in A; R2 (order 2) `FIXED_PER_GOAL` G3 4,000 | R 600; R2 sees 2,900 < 4,000 → `skipped` |
| E | rule_capacity 600; R1 (order 1) FIXED G1 500; R2 (order 2) FIXED G3 400 | R1 500, remaining 100, R2 `skipped`; with R2 `allow_partial`: G3 100 |

---

## 11. AUTO and CONFIRM (P01 APPROVED)

### 11.1 AUTO

- Explicit enable after a preview; pause and disable are always available.
- Internal reservations only; no external movement (P16).
- Executes through the durable dispatcher (§12), in one transaction per
  triggering event (§14).
- Idempotent (§13), recoverable (§12), audited (`rule_execution_audit`).
- No retroactive execution (P46, §16).
- Guaranteed **unattended** execution only with the durable periodic
  dispatcher (P50); otherwise execution happens at the next supported drain.

### 11.2 CONFIRM

- A proposal is an execution in `awaiting_confirmation` with planned items. It
  writes **no** reservation and **no** GoalTransaction, and it may fail at
  confirmation: CONFIRM is not guaranteed execution.
- The user sees the source, the Goals, the amounts, current figures and
  expected figures after execution.
- Expiry: 7 days after creation (P54), applied lazily at read, confirmation and
  dispatch. An expired proposal can never be confirmed; a repeated action
  returns `expired`.

### 11.3 Soft capacity holds (APPROVED P55)

**Approved semantics (P55):**

- A pending proposal holds capacity softly while it is `awaiting_confirmation`
  and `expires_at > now`; the hold ends on `executed`, `rejected`, `expired` or
  `cancelled` (including `superseded`).
- A hold is not reserved money, changes no Account balance and never blocks an
  Expense, a Transfer or a manual reservation.
- Later rule evaluations (AUTO executions and the creation of new proposals)
  subtract **all** active holds on the Account:
  `rule_capacity(A) = reservable(A) − floor(A) − active_holds(A)` (§8.1).
  This keeps P48 priority: a higher-order CONFIRM rule is not overtaken by a
  lower-order AUTO rule.
- A proposal never counts its own hold against its confirmation.

**Confirmation capacity:**

- Confirming proposal X revalidates the real current capacity and requires
  `confirm_capacity(A, X) ≥ Σ planned amounts of X`, where
  `confirm_capacity(A, X) = reservable(A) − floor(A) − prior_holds(A, X)` (§8.1).
- X's own hold is excluded by construction.
- Holds of proposals ordered **before** X still reduce X's capacity.
- Holds of proposals created **after** X do not: those proposals were computed
  with X's hold already subtracted, so a later (lower-priority) hold cannot
  retroactively defeat an earlier proposal merely because it exists (S44).
- `reservable` reflects current reality: an Expense, a Transfer (posted or
  planned outgoing) or a manual reservation made after the proposal was created
  may consume the capacity, so a confirmation can still legitimately become
  stale (§11.4, S39).

**Hold order (APPROVED P80).**

- `rule_executions.hold_sequence BIGINT` comes from a PostgreSQL sequence
  (`nextval`) and is assigned **exactly once**, when an `awaiting_confirmation`
  proposal is created. Creation happens inside the processing transaction that
  already holds L0; a rollback leaves a harmless gap. It is immutable and
  independent of later edits of `execution_order`, rule version or Goal priority.
- Precedence therefore follows processing order: event FIFO (P52) decides
  between events, P28 between rules inside one event, and insertion in that
  order assigns increasing `hold_sequence`. Cross-user sequence order does not
  matter because Accounts are user-owned. `created_at` / `id` are **not** the
  financial precedence mechanism.
- `hold_sequence IS NULL` means the execution was never a proposal; non-NULL means
  it originated as a CONFIRM proposal and **stays populated forever** after it
  becomes `executed`, `rejected`, `expired` or `cancelled`. `expires_at` is the
  immutable proposal expiry timestamp. The database may enforce
  `hold_sequence IS NULL ⇔ expires_at IS NULL`; it must **not** tie
  `hold_sequence` to the current status.

**S44 proof.** Let X have `hold_sequence = 10` and Y `hold_sequence = 11`.
Confirming X subtracts only active holds with sequence `< 10`; Y does not count
against X. If X executes, its real reservation reduces `reservable`. Confirming Y
later uses the new `reservable` and the active holds with sequence `< 11`.
Later soft holds therefore cannot defeat X, while X's real executed reservation
correctly affects Y.

### 11.4 Confirmation procedure

Under locks (L0 → execution → Goals → Account):

1. the rule is enabled, valid and at the proposal's version;
2. the proposal has not been cancelled by a source change (`income.updated` →
   `cancelled (source_changed)`, `income.deleted` → `cancelled (source_deleted)`,
   §15.2); confirmation reads no Income row;
3. the Goals and the Account are active;
4. `confirm_capacity(A, X)` (§8.1, §11.3) covers exactly the proposed amounts.

If all hold: `executed`, GoalTransactions written, hold ended. Otherwise 409
and `cancelled (stale)`, hold ended, nothing written. Nothing is silently
recalculated. A repeated confirmation returns the stored result; rejection
(`rejected`) is final.

### 11.5 Audit codes

proposed, applied, applied_partial, skipped, blocked, confirmed, rejected,
expired, cancelled (superseded / stale / source_changed / source_deleted /
rule_inactive), source_changed, source_deleted. Retries are visible on the
event (§12). Completed executions are never rewritten; annotations are only
appended.

---

## 12. Durable Event Delivery / Outbox (F1)

### 12.1 Options considered

| Option | Atomic with Income | Recovery | Complexity | Verdict |
|---|---|---|---|---|
| Processing only after commit (v0.2) | no | events lost on crash | low | rejected |
| Transactional outbox `financial_events` + database dispatcher | **yes** | yes (leases, retries) | moderate | **chosen** |
| External message broker | no (needs an outbox anyway) | yes | high, new infrastructure | rejected without evidence |

### 12.2 Write

- `income_service` create/update/delete inserts one `financial_events` row in
  the **same** transaction (`commit=False`, single commit) through a narrow
  function of the events module. Types: `income.created`, `income.updated`,
  `income.deleted`.
- A failed Income write rolls back → no event. A committed Income always has its event.
- **Atomicity refactor (E3, APPROVED P83).** Every Income create / update / delete
  writes its `financial_events` row in the same transaction as the canonical
  mutation, and the event repository never commits independently:
  - *create without Account:* today the repository commits itself
    (`commit=commit`); the service path passes `commit=False` to the repository,
    inserts the event with `commit=False`, then commits once in the service;
  - *create with Account:* Income → `AccountTransaction` projection → event → one commit;
  - *update / delete:* existing locks (Income `FOR UPDATE`, then Accounts) remain;
    the event insert precedes the existing single service commit;
  - callers that pass `commit=False` keep both the canonical mutation and the event
    uncommitted for the composing caller;
  - no network call is added under database locks (FX is resolved before the locks).
- **Schema (§19.3, APPROVED P83):** explicit typed provenance and snapshot columns
  (`origin`, `ingestion_mode`, `snap_*`); core filtering and eligibility fields are
  never hidden in JSONB. `aggregate_id` is a **soft** reference (no FK to Income, so
  `income.deleted` events survive the deletion). `outcome_summary` holds
  non-monetary codes only.
- **Provenance of the current manual Income API:** create → `manual/live` when
  `received_at ≥ created_date − 7 days`, otherwise `manual/historical` (P51);
  update → `manual/correction`; delete → `manual/correction`. Income created before
  E3 has no `income.created` event and is therefore historical: never retroactively
  AUTO-eligible. The Income table gets no provenance column.
- The event stores provenance (§16), a typed source snapshot (`amount`,
  `currency`, `received_at`, `account_id`, `income_source`,
  `aggregate_updated_at`) and `not_before` (start of the `received_at` day for a
  future-dated Income, otherwise now).

### 12.3 Event states

| Status | Meaning | Terminal |
|---|---|---|
| `pending` | committed and waiting (possibly deferred by `not_before`) | no |
| `processing` | claimed (`claim_token` set); `lease_expires_at` set; `attempts` already incremented | no |
| `processed` | handled; `outcome_summary` holds non-monetary codes | yes |
| `failed_retryable` | technical failure; `next_attempt_at` set | no |
| `dead` | `attempts ≥ max_attempts`; visible to the user and operations; manual re-queue allowed | yes (until re-queued) |

Delivery is at least once. The exactly-once **financial effect** comes from
execution uniqueness (§13), not from delivery.

### 12.4 Claim and process (APPROVED P52, P82)

1. **Claim** (short, durable transaction): `status = 'processing'`, `attempts + 1`,
   new `claim_token`, `lease_expires_at = now + 5 minutes`, only if the event is the
   user's claimable head (below). Counting attempts before processing bounds events
   that crash the process.
2. **Process** (one transaction per event, §14): L0 → event `FOR UPDATE` →
   verify the `claim_token` and that the event is still the user's head under the
   P52 selection → rules → executions → Goals → Account → writes → `processed` →
   commit.
3. **Technical error:** the business transaction rolls back (including any
   execution row), then a short follow-up transaction sets `failed_retryable` with
   `next_attempt_at` per the constants below, or `dead` after the sixth failed
   attempt; `deadlock_detected` and serialization failures are retryable.
4. **Crash** after the claim: the lease expires; if `attempts < max_attempts` the
   event becomes claimable again, a reclaim starts a new attempt and increments
   `attempts` again. **Max-attempt recovery:** if the user's selected FIFO head is
   `processing` with `lease_expires_at <= now()` and `attempts >= max_attempts`
   (6), it is **never** reclaimed and no seventh attempt exists. In the short
   claim / recovery transaction it becomes terminal `dead`:
   `status = 'dead'`, `last_error_code = 'lease_expired_max_attempts'`,
   `lease_expires_at = NULL`, `next_attempt_at = NULL`. This is recovery of an
   abandoned max-attempt lease, **not** a business execution result. A `dead`
   event no longer blocks that user's newer events, so the head never wedges the
   FIFO queue (the `attempts BETWEEN 0 AND 6` CHECK is never violated).
5. **Business outcomes** (`executed`, `skipped`, `blocked`, a proposal, "not
   eligible") are committed outcomes and are **never** technical retries.

**Strict per-user FIFO (APPROVED P52).** For one user, unfinished events
(`pending`, `processing`, `failed_retryable`) are ordered by `occurred_at ASC, id ASC`.

1. **Head selection comes first.** Among the user's unfinished events that are not
   business-date deferred (`not_before IS NULL OR not_before <= now()`), the
   **head** is the first one in that order. An event with `not_before > now()` does
   not take part in head selection at all, so it does not block newer due events;
   when `not_before` arrives it re-enters normal `(occurred_at, id)` order.
2. **Only then** decide whether the head is claimable:
   - `pending`; or
   - `failed_retryable` **and** `next_attempt_at <= now()`; or
   - `processing` **and** `lease_expires_at <= now()`.
3. If the head is `processing` with a live lease, or `failed_retryable` whose
   `next_attempt_at` is still in the future, the user is **BLOCKED**: no newer
   event of that user may be selected.
4. `processed` and `dead` events never block. An event committed late is processed
   when it becomes visible.

A query that filters to "claimable rows" **before** choosing each user's
`DISTINCT ON` / `row_number()` head would let a newer event bypass a waiting older
one and **violates P52**. The reference shape is: select each user's head over all
unfinished, non-deferred events first (for example
`SELECT DISTINCT ON (user_id) … ORDER BY user_id, occurred_at, id`), and apply the
claimable predicate to that head afterwards. L0 serializes the actual processing
per user and the head is re-verified under L0; `SKIP LOCKED` may be used only for
cross-user claim concurrency and must never let one user's newer event bypass an
older blocking one.

**Constants (APPROVED P82):** lease 5 minutes; `max_attempts = 6`; delays after
failed attempts 1–5: 1 minute, 5 minutes, 30 minutes, 2 hours, 12 hours; the sixth
failed attempt → `dead` (and an expired lease at `attempts = 6` → `dead` with
`lease_expired_max_attempts`, step 4); **no jitter** in v1. `dead` events stay
visible to the user and operations.

**Manual re-queue (operational action).** `dead → pending`, resetting the retry
cycle: `attempts = 0`, `next_attempt_at = NULL`, `lease_expires_at = NULL`,
`claim_token = NULL`, `last_error_code = NULL`, `processed_at = NULL`. It preserves
the event `id`, `user_id`, `event_type`, aggregate / source identity, source
snapshot, provenance, `occurred_at` and `not_before`; it never creates a new
`financial_events` identity. The event is again subject to normal FIFO ordering
by its original `(occurred_at, id)`, and if `not_before` is still in the future the
normal business-date deferral applies. A re-queue never creates or reopens a
committed `rule_execution`; execution uniqueness (§13.4) stays authoritative, so a
re-processed event finds its stored execution (eligibility predicate E10, §15.1) and replays it. A re-queue is
auditable through logs / operations; E1 adds **no** new event-audit table.

### 12.5 Consumption and guarantees

| Mechanism | Durable | Guarantee |
|---|---|---|
| (a) Best effort after the response (e.g. FastAPI `BackgroundTasks` in the same process) | no | usually within seconds; may be lost on a crash, but the event stays `pending` |
| (b) User-triggered drain: `POST /api/v1/financial-rules/evaluate` on app foreground and Inbox open; at most N due events of **that** user | yes (reads the outbox) | processed at the user's next activity |
| (c) Durable periodic dispatcher (APPROVED requirement P50) | yes | eventual processing **without** user activity, within the configured cadence (target ≈ 10 min) |

- Mechanism (c) is required before `AUTO` is presented as guaranteed unattended
  automation (GA) (APPROVED P50). The approved boundary (P87): a **separate
  scheduled process** (the preferred mechanism is a Render Cron Job) invoking a
  backend CLI entrypoint (for example `python -m app.modules.financial_rules.dispatcher`)
  about every 10 minutes (range 5–15), using the same database and application
  code, with bounded batches. An in-process lifespan / asyncio loop **does not
  satisfy P50** (a process restart or sleep stops it). `BackgroundTasks` (a) are
  best effort only; the authenticated evaluate (b) is a user-triggered durable
  drain only; neither is the unattended guarantee. There is no public cross-user
  dispatcher endpoint. **P50 TECHNICAL VERIFICATION STILL REQUIRED:** the repository
  proves no scheduler (the API image runs `uvicorn` only; there is no worker, no
  scheduler dependency and no Render blueprint); the actual Render plan and
  Cron Job capability must be verified in VF-020E10 before any unattended claim.
- Without (c), a beta must truthfully state that `AUTO` executes after the
  transaction and at the latest at the next supported user-triggered drain.
- A message broker is not needed.

### 12.6 Bounded queries

The dispatcher reads only `financial_events` through partial indexes on due
statuses; it **never scans** `income`. Batches: K users per pass, at most M
events per user.

### 12.7 Failure cases

| Failure | Outcome |
|---|---|
| Income rolled back | no event |
| Crash after commit, before dispatch | event stays `pending` → (b) or (c) |
| Crash during processing | rollback; lease expires; retried while `attempts < 6`, otherwise `dead` (`lease_expired_max_attempts`) |
| Business rule outcome | terminal execution (`blocked`/`skipped`); event `processed` |
| Technical error | `failed_retryable` → retries → `dead` |
| Source changed after the event | detected via snapshot vs `aggregate_updated_at` (§15) |
| Duplicate dispatch | the second worker sees `processed` under L0 → no-op |

### 12.8 Operational readiness

Metrics: counts per event status; age of the oldest unfinished, non-deferred
event; processing time; attempt distribution. Alerts: such an event older than
~3× the dispatcher cadence (with (c) enabled); any `dead` event. A runbook for `dead` events.
Logs contain no amounts or personal data beyond identifiers.

### 12.9 Retention

Processed events are kept as the durable provenance record (§16) until the user's
data is deleted; VF-020E performs **no** time-based cleanup (APPROVED P53 for the
VF-020E technical behavior). Any later legal or provider retention requirement is
external review (VF-021 / legal, EXT).

---

## 13. Execution State Machine and Idempotency (F2)

### 13.1 Four entities

| Entity | Storage | Identity |
|---|---|---|
| Source-trigger event | `financial_events` | `id`; `income.created` unique per Income |
| Evaluation attempt | `financial_events.attempts`, `last_error_code`, timestamps (no separate table) | (event, attempt number) |
| Financial execution (one rule's decision about one source) | `rule_executions` + `rule_execution_items` | `UNIQUE(user_id, rule_id, source_type, source_id)` |
| CONFIRM proposal | the **state** `awaiting_confirmation` of that execution | same as the execution |

Audit: `rule_execution_audit`, append-only, records every transition and annotation.

### 13.2 Retry vs uniqueness

An execution row is created **only inside the successful processing
transaction**. A technical failure rolls the row back as well, so the retry
sees no row and evaluates again. A **business** outcome (executed, skipped,
blocked, proposal) is a committed row and is the final decision. Hence E10: "no
**committed** execution exists for (R, I)": retries are possible, duplicates
are not.

### 13.3 Execution states

| State | Terminal | Retry | Reopens after source change | Confirmable | Writes goal rows | Duplicate request | Audit |
|---|---|---|---|---|---|---|---|
| `awaiting_confirmation` | no | — | no; a source change → `cancelled` | **yes** | no (only on confirmation) | returns the proposal | proposed |
| `executed` | yes | no | no; annotations only | no | **yes**, once, in the same transaction | replay | applied |
| `executed_partial` | yes | no | no; annotations only | no | **yes** | replay | applied_partial |
| `skipped` | yes | no | no | no | no | replay | skipped + reason |
| `blocked` | yes | no | no | no | no | replay | blocked + reason |
| `rejected` | yes | no | no | no | no | replay | rejected |
| `expired` | yes | no | no | no | no | replay | expired |
| `cancelled` | yes | no | no | no | no | replay | cancelled + reason |

"Not eligible" is **not** stored as an execution; it is recorded in the event's
`outcome_summary`. A later correction can therefore make the Income eligible,
but only within the provenance and window rules of §15–§16.

### 13.4 Unique key `UNIQUE(user_id, rule_id, source_type, source_id)`

| Case | Supported | How |
|---|---|---|
| Retry after a technical failure | yes | no committed row → evaluated again |
| Rule edit / new version | yes | the key excludes the version; historical Income is **not** executed again; open proposals → `cancelled: superseded` |
| Disable / re-enable | yes | `active_since` reset; Income from the disabled period is not eligible (E5) |
| Expired / cancelled proposal | yes | terminal; **no** new proposal for the same source |
| Manual evaluation | yes | only drains events; creates no new identities |
| Repeated delivery | yes | row exists → replay |
| Backfill suppression | yes | not eligible by provenance → no row; provenance is permanent, so it never becomes eligible |
| Bypass through a new identity | **forbidden** | `source_id` is always the canonical Income id; a new id exists only for a new canonical record with its own provenance |

---

## 14. Deterministic Concurrency and Lock Ordering (F3)

### 14.1 Options

| Option | Atomicity | Partial failure | Retry | Lock duration | Rule order |
|---|---|---|---|---|---|
| 1. One transaction for all rules of one event | all or nothing per event | impossible (rollback) | whole event, deterministic | short | **guaranteed** within the event |
| 2. One transaction per rule + claiming | per rule | possible | per rule | short | needs extra serialization; an Account row lock alone does not enforce priority |
| 3. Database dispatcher with per-user coordination | — | — | leases | — | orders events relative to each other |

**Design (APPROVED): 1 + 3.** All rules of one event are processed in one
transaction in P48 order with a running capacity; events of one user are
serialized by the user lock L0, in strict per-user FIFO order (APPROVED P52;
§14.4).

### 14.2 Global lock order

| Level | Lock | Taken by |
|---|---|---|
| L0 | `pg_advisory_xact_lock(key(user_id))`, key per §14.5 (P68, P69) | **every** write of the goals and financial-rules modules: manual goal transactions, Goal CRUD/archive, priority reorder (VF-020D); rule create/edit/state, confirm/reject, dispatcher (VF-020E) |
| L1 | event `FOR UPDATE`, then execution rows (`INSERT … ON CONFLICT DO NOTHING` + `SELECT … FOR UPDATE`) | dispatcher, confirm/reject |
| L2 | Goals `FOR UPDATE`, ascending UUID (all targets of all rules, locked together) | goal-financial paths |
| L3 | Accounts `FOR UPDATE`, ascending UUID | goal-financial paths |
| — | canonical row → Accounts ascending UUID (INV-05) | existing Income/Expense/Transfer/adjustment paths, **unchanged** |

Cycle analysis:

- Existing canonical paths never take or wait on L0–L2; they hold a canonical
  row plus Accounts.
- VF-020 paths never lock Income, Expense or Transfer rows; the dispatcher reads
  the Income without a lock and compares the snapshot. Planned Transfers are
  read without locks for `planned_transfer_out`.
- The only shared lock class is L3, which both families take last, so the
  design has no lock cycle by construction.
- Account lifecycle paths lock the Account and only **read** goal references.
- FK checks: inserting a goal row takes `KEY SHARE` on a Goal and an Account the
  transaction already holds `FOR UPDATE`; deleting an Account checks append-only
  `goal_transactions`, which are never updated.
- Cross-user: L0 keys differ; a hash collision only serializes two users.
- No network calls under locks: FX is resolved by Income before its locks; the
  dispatcher performs no network calls.

Deadlock freedom is a **design claim** that must be confirmed by CT-01…CT-12
(§25); any `deadlock_detected` is handled as a retryable failure.

**VF-020C lock order (APPROVED P61, superseded by P68 from VF-020D).** L0 is
**not** introduced in VF-020C (it is introduced in VF-020D, §14.5). The manual paths use row locks only, in this order,
which is a subset of the global order above:

1. fast lookup by `(user_id, client_request_id)` without row locks; when the key
   is unused, end that read transaction (B3: no `goal_transactions` lock may be
   held while waiting for `goals`);
2. Goal `FOR UPDATE` (L2);
3. Account `FOR UPDATE` (L3) - linked contribution only; a linked
   withdrawal/release takes no explicit Account lock (the insert's foreign-key
   check takes `KEY SHARE` on the Account row after the Goal lock);
4. second key lookup, lifecycle checks, partition or capacity check, insert.

The Account lock serializes concurrent reservations on one Account across
different Goals, so the capacity check cannot be defeated by a race. Expense,
Transfer and adjustment paths (canonical row → Accounts) never lock Goals, so
reservations do not block them beyond a short Account-lock wait (P05). The
Account delete and currency-change pre-checks (P65) hold the Account lock and
only read `goal_transactions`.

Two different orders must not be confused. The **C1 migration's table-lock
order** is `accounts` → `goal_transactions` (table locks taken before any DDL).
The **C2 runtime row-lock order** is Goal → Account → `goal_transactions`
interaction (above). They are not the same order and this contract does not
claim they are. They do not conflict, because C1 is applied to production
**before** any C2 runtime code is deployed (§28): while the migration runs, no
code that reads or writes `goal_transactions.account_id` exists yet. A linked
contribution locks Goal then Account; a linked withdrawal/release may take no
explicit Account lock, which does not change the approved ordering rule for
every path that locks both entities (Goal first, then Account). No new product
decision is implied.

From VF-020D (§14.5) L0 wraps every Goal write, manual ones included; the
VF-020C row-lock order above then runs *after* L0.

### 14.5 VF-020D: L0 contract (APPROVED P68, P69)

**Scope.** L0 is the user-wide, transaction-scoped PostgreSQL advisory lock
`pg_advisory_xact_lock(bigint)`. Once introduced in VF-020D it is taken by
**every** Goal write:

| Goal write | L0 |
|---|---|
| Goal create | yes |
| Goal PATCH / edit / status transition | yes |
| Goal DELETE | yes |
| tracked contribution | yes (new write) |
| tracked withdrawal | yes (new write) |
| linked contribution | yes (new write) |
| linked withdrawal / release | yes (new write) |
| priority reorder | yes |
| read-only Goal requests (`GET`) | no |
| occupied-key idempotent replay that performs no new Goal write | no |
| Account delete, Account currency change | **no** (existing Account-lock and read-reference semantics are retained) |

**Order.** `L0(user)` → Goal row(s), ascending id when several → Account
row(s) where applicable → `goal_transactions` interaction.

**B3/C2 fast path preserved.** An initial lookup of an occupied
`client_request_id` happens before the write transaction and holds no row
locks. If the key resolves to a stored transaction the replay (or conflict) is
returned without L0. If the key is unused the lookup transaction is **ended**,
and then the write transaction runs: `L0` → Goal `FOR UPDATE` → Account
`FOR UPDATE` where required → second idempotency lookup → validation → write.
No `goal_transactions` lock may be held while waiting for L0 or `goals`.

**Key derivation (identical in every implementation).**

```python
digest = sha256(b"valor-finis:l0:user:v1:" + user_id.bytes).digest()
lock_key = int.from_bytes(digest[:8], byteorder="big", signed=True)
```

The lock is acquired through the **same** SQLAlchemy session and transaction
that performs the write, with no Python `hash()`, no network call under L0 and
no use of a different connection. It is released at commit or rollback. A hash
collision may serialize two unrelated users briefly; it can never mix
ownership or data.

**No-cycle analysis.** Every L0 holder takes L0 first and never waits for L0
while holding a Goal or Account row lock. The remaining orders are the
approved Goal → Account order (C2). Account lifecycle paths lock only the
Account and read `goal_transactions` references; they take no Goal lock and no
L0, so there is no Account → Goal or Account → L0 edge. Reorder locks Goals in
ascending id under L0; two reorders, or a reorder and any other Goal write,
are serialized by L0. Canonical Income/Expense/Transfer paths lock their own
row and Accounts and never Goals or L0. Different users never share a lock
except by hash collision. Deadlock freedom remains a design claim to be
confirmed by the VF-020D concurrency tests (§25).

### 14.3 Timeline: higher-priority rule wins (S31)

Setup: CHK `rule_capacity` = 600. R1 (order 1) FIXED G1 500, AUTO. R2 (order 2)
FIXED G3 400, AUTO. Salary event E. Worker W1 (after-response task) and worker
W2 (drain) start together.

```
t0  W1: claim E (processing, attempts=1)     W2: claim fails (E is processing, lease active)
t1  W1: BEGIN; L0(user) acquired
t2  W1: E FOR UPDATE; any older unfinished event of the user blocking E (P52)? no
t3  W1: load enabled rules [R1, R2] ordered by (execution_order, created_at, id)
t4  W1: insert-or-get executions (R1, income), (R2, income) FOR UPDATE
t5  W1: lock Goals {G1, G3} ascending; lock CHK
t6  W1: capacity 600 → R1 500 → executed; running 100
                    → R2 400 > 100, allow_partial = false → skipped (insufficient_capacity)
t7  W1: insert goal_transactions (G1, CHK, 500, rule_execution_id = R1 execution); E processed; COMMIT
t8  W2: later drain → E processed → no-op
```

A concurrent manual reservation M (G3, 400, CHK) is serialized by L0: if M runs
first, reservable becomes 200 and both R1 and R2 are `skipped`; if W1 runs
first, M sees reservable 100 and gets 409. Both outcomes are deterministic and
neither violates P48 within the event.

### 14.4 Separate events for one Account (APPROVED P52)

Serialized by L0, in strict per-user FIFO order (`occurred_at ASC`, `id ASC`); the
exact head-selection and claim semantics are in §12.4:

- A user's older unfinished event (`pending`, `processing` with a live lease,
  `failed_retryable`) blocks that user's newer events.
- Exception: an event deferred because its business date has not arrived yet
  (`not_before` in the future) is excluded from head selection and does **not**
  block currently due newer events; once due it participates normally.
- A technical retry in `failed_retryable` **does** block newer events
  (head-of-line), including while it waits for `next_attempt_at`.
- `processed` and `dead` never block; once an event becomes `dead`, newer events continue.
- FIFO applies to *committed* events; an event that commits after a newer one
  was processed is processed when it becomes visible.

---

## 15. Income Eligibility and Correction Handling

### 15.1 Predicates (P35, P46, P51 APPROVED; formalization below)

Evaluated when an event is processed, against the **current** Income state.

| # | Predicate | On failure |
|---|---|---|
| E1 | Income, rule and event belong to one user | not eligible |
| E2 | Income is linked to `R.source_account_id` | not eligible |
| E3 | `received_at ≤ D` | event **deferred** (`not_before = received_at`) |
| E4 | The Income's **creation** event has provenance `manual/live` (v1; `import/live` only in VF-021 under its policy) | not eligible (permanent) |
| E5 | The creation event occurred at or after `R.active_since`, and `received_at ≥ R.effective_from` | not eligible (permanent) |
| E6 | `received_at ≥ date(triggering_event.occurred_at) − 7 days` (inclusive; P51) | not eligible |
| E7 | `income.source ∈ R.income_sources` (`refund` excluded by default) | not eligible |
| E8 | Income/Account currency = every target Goal's currency | `blocked` |
| E9 | Account active; targets active (archived → blocked; completed → allowed, P11); rule valid | `blocked` |
| E10 | No **committed** execution exists for (R, I) | replay / annotation |

### 15.2 Processing by event type

- `income.created`: E1–E10 for every enabled rule in P48 order.
- `income.updated`: existing `executed` / `executed_partial` → audit
  `source_changed` when the snapshot differs; `awaiting_confirmation` →
  `cancelled (source_changed)` (hold ends); no row → E1–E10, where E6 is
  measured from the **update** time while E4/E5 still use the **creation**
  provenance, so an old Income can never become eligible through an edit.
- `income.deleted`: executions get `source_deleted`; proposals →
  `cancelled (source_deleted)` (hold ends); floor and overcommitment alerts are
  re-evaluated; **no compensating entries** (P47).

### 15.3 Corrections after execution (P47)

| Change | Execution | Reservations | Derived state | User |
|---|---|---|---|---|
| Amount decreased | `source_changed` annotation | unchanged | recomputed | alert + "Release" option |
| Amount increased | annotation; **no** additional allocation | unchanged | recomputed | option to top up manually |
| Date moved into the future | annotation | unchanged | `balance_as_of` decreases; may become overcommitted | alert |
| Date moved earlier | annotation | unchanged | recomputed | info |
| Moved to another Account | annotation | **stay** on the original Account | original loses capacity, new gains it | alert if overcommitted |
| Unlinked from its Account | annotation | stay | capacity decreases | alert if overcommitted |
| Deleted | `source_deleted`, snapshot kept | stay | recomputed | alert + "Release" option |
| Late historical entry | — (E4/E5/E6) | — | — | Income recorded normally |
| Duplicate trigger | replay (E10) | — | — | — |
| Technical failure | no row; event retried | — | — | `dead` visible |

---

## 16. Historical Import Provenance (F4)

### 16.1 Owner and form

Provenance belongs to the **events module**. It is set by the module that
performs the canonical mutation, at mutation time, in the same transaction.
`income.source` (salary/…/refund) is **not** overloaded, and VF-020 adds **no**
column to `income`. VF-021 adds its own import-link record (imported event →
canonical record, sync run, batch) carrying the same classification.

- `origin` ∈ {`manual`, `receipt`, `import`, `system`}
- `ingestion_mode` ∈ {`live`, `historical`, `correction`}

The provenance of an Income is the `origin` / `ingestion_mode` of its unique
`income.created` event. An Income created before VF-020 has no creation event
and is treated as `historical`: never eligible.

### 16.2 Classification

| Situation | origin / mode | AUTO-eligible |
|---|---|---|
| Manual Income with `received_at ≥ created_date − 7 days` (future dates included, deferred) | manual / live | yes (E1–E10) |
| Manual Income with `received_at < created_date − 7 days` | manual / historical | **no** |
| Correction of an existing Income | manual / correction (`income.updated`) | first eligibility only per §15.2 |
| Live import (incremental sync, VF-021) | import / live | yes, only through the canonical Income and only if the import posting policy allows (P23) |
| Historical backfill / reconnect (VF-021) | import / historical | **no** |
| Duplicate provider delivery | no canonical change → **no event** | — |
| Pending → booked (VF-021) | import / correction, or a match to an existing record | no new execution |
| Reclassification Expense → Income (VF-021) | import / correction | **no** (PROPOSED) |
| Receipt-derived record | receipt (creates an Expense, not Income) | not a trigger in v1 |
| Reconciliation with an existing manual record | evidence link, no new canonical record | — |

For VF-021, classification comes from the import provenance (sync run type,
batch), never from timestamps alone (P51). For the current manual Income API the
classification is fixed by §12.2 (create: live or historical by the 7-day boundary;
update and delete: correction).

### 16.3 Guarantees

An old transaction imported today is not a new economic event. Reconnects,
duplicates and reclassifications do not re-run rules. A manual historical entry
does not become eligible merely because it was just created. `received_at` and
`created_at` keep their meaning; Income and Financial Overview semantics do not
change.

---

## 17. Budgets Integration (P40 EST)

- Budgets are the **only** source of spending limits; rules store no limits and
  no periods.
- `BUDGET_ALERT` uses the same computation as
  `GET /api/v1/analytics/budget-status` (`budget_metrics`), preserving the
  weekly/monthly/yearly semantics.
- It fires on transitions to `watch`, `at_risk` or `exceeded` per
  `(budget_id, period_start)`; deduplicated per level per period
  (`rule_alerts` unique key); only escalations re-alert.
- Alerts are evaluated during drains, manual evaluation and periodic recovery:
  detection happens at the next evaluation, not in real time.
- Optional internal guard on allocation rules ("skip if the selected Budget is
  `exceeded`"): PROPOSED, may be deferred.
- **An alert never blocks an Expense.**
- **Ownership (APPROVED P84).** `BUDGET_ALERT` carries `budget_id` with the ownership
  FK `(budget_id, user_id)` → `budgets(id, user_id)` ON DELETE RESTRICT. The current
  `budgets` table has no composite unique key, so the E4 migration adds
  `UNIQUE (id, user_id)` on `budgets` before the FK is used. Deleting a Budget that a
  rule references returns a controlled 409 **before** the FK can fail. The rule
  reuses the authoritative budget-status calculation
  (`analytics_service.get_budget_status` / `budget_metrics`); it must **not**
  introduce a second budget formula. That function currently loads all of the
  user's expenses and budgets, so the alert stage extracts or refactors it into a
  bounded per-Budget evaluation that preserves the same semantics.
- **Alert-rule uniqueness (APPROVED P84).** Partial `UNIQUE` constraints:
  `MINIMUM_UNALLOCATED_FLOOR` one per `(user, Account)`; `OVERCOMMITMENT_ALERT` one
  per `(user, Account)`; `BUDGET_ALERT` one per `(user, Budget)`. Duplicate alert
  rules that would produce duplicate notifications for one subject are not allowed.
- **Alert storage is deliberately not final here (APPROVED P85).** The physical
  `rule_alerts` schema is finalized in the later stage E9A, because Budget
  alerts need deduplication and transition semantics (`subject_type`, `subject_id`,
  `period_key`, `level`, unique per alert transition / level). E1 documents the
  required semantics only; `rule_alerts` is **not** created in E4.

---

## 18. Goal, Account and Rule Lifecycle

| Object | Action | Contract |
|---|---|---|
| Goal | create / edit | currency validation hardened (G1); under L0 from VF-020D (P68); create appends the rank last (P70) |
| Goal | archive | allowed; `priority_rank = NULL`, no compaction (VF-020D, P70); new contributions (tracked and linked) → 409 (P10); tracked and linked withdrawals and releases allowed; an enabled allocation rule targeting it becomes invalid and future execution is `blocked (target_goal_archived)` (VF-020E, P37) |
| Goal | complete | manual status; no restrictions (P11) |
| Goal | delete | only without history (EST); also controlled 409 if referenced by `financial_rule_goal_targets` (APPROVED P57); the 409 pre-check runs before any FK failure |
| Goal | currency | immutable once history exists (EST); an actual currency change while referenced by a rule target → controlled 409 (P57); composite FK as last line of defense |
| Account | archive | allowed; reservations kept; new linked contributions → 409; linked withdrawals/releases allowed; the reserve is never moved to another Account; rules referencing it become invalid and are `blocked (source_account_archived)` (VF-020E, P37); a configured floor stays stored |
| Account | delete | pre-checks: ledger history (EST), planned Transfers (EST), **any historical linked GoalTransaction** (P65, even at zero net), references by any `financial_rules` row including floor and alert rules (VF-020E, P57) → controlled 409 before the RESTRICT FK |
| Account | currency | pre-checks: history, planned Transfers, **any historical linked GoalTransaction** (P65), an actual currency change while referenced by any `financial_rules` row (VF-020E, P57) → controlled 409 |
| Rule | create / edit | under L0; validation; a material edit (§10.3) increments `version` and cancels open proposals (`superseded`); `name`, `description`, `execution_order` are non-material |
| Rule | enable | `active_since = now()` on every transition into `enabled`; preview required for `AUTO` (P88) |
| Rule | pause / disable | events processed without it; proposals → `cancelled (rule_inactive)` |
| Rule | delete | final rule: only when the rule has **no** `rule_executions`; otherwise controlled 409 and the user must disable it; dependent target rows cascade with the rule; informational notification rows never redefine this rule (APPROVED P57). **Stage ownership:** E5 DELETE has no execution-history pre-check, because no `rule_executions` schema or runtime exists at E5; E6 adds the RESTRICT FK as a backstop but no execution-creating runtime; **E7 ships the `rule_executions` pre-check in the same release that first lets AUTO create executions** (under L0, controlled 409, never relying on the FK failure); E8 inherits it |
| Budget | delete | controlled 409 when referenced by a `BUDGET_ALERT` rule, before the ownership FK can fail (P57, P84) |
| Income | create / update / delete | unchanged behavior + one outbox event in the same transaction |
| Transfer | planned / post / delete | unchanged; affects capacity per §8 (P49) |

---

## 19. Database Schema (implemented B/C/D schema; final VF-020E contract — each migration is a separate approval)

### 19.1 `goals` (VF-020B; rank in VF-020D)

`uq(id, user_id)`, `uq(id, user_id, currency)`;
`CHECK status IN ('active','completed','archived')`;
`CHECK currency ~ '^[A-Z]{3}$'`; `priority_rank INTEGER NULL` with
`CHECK (priority_rank IS NULL OR priority_rank >= 1)` and
`UNIQUE (user_id, priority_rank) DEFERRABLE INITIALLY DEFERRED` (VF-020D2,
P72); the lifecycle check `(status = 'archived') = (priority_rank IS NULL)` is
added only in VF-020D5;
`description VARCHAR(255) NULL` (PROPOSED).

### 19.2 `goal_transactions` (VF-020B/C)

Columns per §7.3. Implemented by VF-020B: `currency NOT NULL`,
`effective_date`, `client_request_id`; FKs `(goal_id, user_id, currency)` →
`goals`, `(goal_id, user_id)` → `goals` and `goal_id` → `goals` (all RESTRICT);
`UNIQUE(user_id, client_request_id)`.

**VF-020C1 schema candidate (APPROVED P66) - the only schema change of VF-020C:**

| Item | Definition |
|---|---|
| Column | `account_id UUID NULL`; no default; **no backfill** (legacy rows stay NULL); not ORM-mapped until VF-020C2 |
| FK | `fk_goal_transactions_account_id_user_id_currency`: `(account_id, user_id, currency)` → `accounts(id, user_id, currency)` ON DELETE RESTRICT; reuses the existing `uq_accounts_id_user_id_currency`; with `account_id IS NULL` the (MATCH SIMPLE) key is not enforced, so tracked rows are unaffected. Goal/Account currency equality follows by transitivity through the existing Goal FK |
| CHECK | `type <> 'opening_balance' OR account_id IS NULL` |
| CHECK | `account_id IS NULL OR client_request_id IS NOT NULL` |
| CHECK | `account_id IS NULL OR effective_date IS NOT NULL` |
| Index | partial `(account_id) WHERE account_id IS NOT NULL` (aggregation of `reserved(A)` and the RESTRICT foreign-key check) |
| Migration locks | `accounts`, then `goal_transactions`, before any DDL; no hard-coded `lock_timeout` (execution-time decision) |
| Not in VF-020C | `rule_execution_id` (VF-020E), any provenance/source column, a separate allocations table, `Account.floor` (P60) |

**VF-020E6 evolution (APPROVED P81, P86).** `rule_execution_id UUID NULL` is added with the
composite FK `(rule_execution_id, user_id)` → `rule_executions(id, user_id)` ON DELETE RESTRICT.
`client_request_id` is `UUID NULL` in the current schema. The linked-key CHECK
`ck_goal_transactions_linked_requires_client_request_id` is replaced by a broadened one, and
two more CHECKs are added:

| Constraint | Definition |
|---|---|
| linked origin (`ck_goal_transactions_linked_requires_origin`, replaces the C1 key CHECK) | `account_id IS NULL OR client_request_id IS NOT NULL OR rule_execution_id IS NOT NULL` |
| mutual exclusivity (`ck_goal_transactions_origin_exclusive`) | `client_request_id IS NULL OR rule_execution_id IS NULL` |
| rule row shape (`ck_goal_transactions_rule_execution_shape`) | `rule_execution_id IS NULL OR (account_id IS NOT NULL AND type = 'contribution')` |

A manual linked row keeps `client_request_id` set and `rule_execution_id` NULL. A rule-generated
row has `type = 'contribution'`, `account_id` = the rule's source Account, `rule_execution_id` =
the execution, `client_request_id = NULL`, `effective_date` = server today and the Goal's /
Account's currency. **No fake `client_request_id` is generated for system allocations.** Legacy
and tracked rows stay valid (every new CHECK is a no-op when both columns are NULL). The existing
CHECK is replaced inside one migration transaction; the replacement accepts every row the old one
accepted, so the pre-E6 runtime keeps working against the new schema. The linkage
`rule_execution_items.goal_transaction_id → goal_transactions(id)` (UNIQUE) is part of the
exactly-once / audit proof.

### 19.3 New tables (each with the Supabase Data API REVOKE) — final E contract (APPROVED P78–P88)

Money columns use `NUMERIC(12,2)` like the existing money columns. **Documented exception (VF-020E6):** the three capacity-snapshot columns of `rule_executions` (`capacity_reservable`, `capacity_floor`, `capacity_holds`) are `NUMERIC(18,2)`: they are signed aggregates (sums over arbitrarily many ledger rows, like `AccountResponse.current_balance`, which has no `max_digits` for the same reason), so they can exceed the range of one canonical money row, and a `NUMERIC(12,2)` column would make the E7 insert fail with a numeric overflow. Every canonical amount column (`source_amount`, `planned_amount`, `applied_amount`, `floor_amount`, `amount_or_cap`) stays `NUMERIC(12,2)`. Every user-owned table
has `user_id`, `UNIQUE (id, user_id)` where it is an FK target, and the Data API REVOKE
pattern of `1edb74dc96d8` / `edcfdf3f7114`. **Rejected:** `accounts.minimum_unallocated_floor`
(the floor is a rule row, §10.6).

| Table | Key fields |
|---|---|
| `financial_events` (E2) | `id`, `user_id`, `event_type` (`income.created` / `income.updated` / `income.deleted`), `aggregate_type`, `aggregate_id` (**soft** reference, no FK to Income), `origin` (`manual`/`receipt`/`import`/`system`), `ingestion_mode` (`live`/`historical`/`correction`), typed snapshot (`snap_amount NUMERIC(12,2)`, `snap_currency`, `snap_received_at`, `snap_account_id`, `snap_income_source`, `snap_aggregate_updated_at`), `occurred_at`, `status` (`pending`/`processing`/`processed`/`failed_retryable`/`dead`), `not_before`, `attempts`, `next_attempt_at`, `lease_expires_at`, `claim_token`, `last_error_code`, `processed_at`, `outcome_summary JSONB` (non-monetary codes only). Partial `UNIQUE(aggregate_id) WHERE event_type = 'income.created'`; partial index `(user_id, occurred_at, id)` on non-terminal statuses; index `(status, not_before, next_attempt_at)`; CHECKs on enumerations and `attempts BETWEEN 0 AND 6` |
| `financial_rules` (E4) | `id`, `user_id`, `name`, `description`, `rule_type` (`INCOME_ALLOCATION` / `MINIMUM_UNALLOCATED_FLOOR` / `OVERCOMMITMENT_ALERT` / `BUDGET_ALERT`; **all four in the CHECK from E4**), `status`, `version`, `active_since`, `source_account_id` + ownership FK `(source_account_id, user_id)` → `accounts(id, user_id)` RESTRICT (**no currency column**), `budget_id` (BUDGET_ALERT only; FK `(budget_id, user_id)` → `budgets(id, user_id)` RESTRICT), allocation-only: `execution_mode`, `execution_order INT`, `effective_from DATE`, `policy`, `percent`, `cap_at_target`, `allow_partial` (default false), `income_sources text[]` (CHECK subset); floor-only: `floor_amount NUMERIC(12,2) CHECK (>= 0)`; per-type CHECKs (type-specific columns NOT NULL for their own type and NULL otherwise; floor/alert types have no `execution_mode`/`execution_order`); partial uniques: floor per `(user_id, source_account_id)`, OVERCOMMITMENT per `(user_id, source_account_id)`, BUDGET_ALERT per `(user_id, budget_id)`; **no** `UNIQUE (user_id, execution_order)`; timestamps; `uq(id, user_id)` |
| `financial_rule_goal_targets` (E4) | `id`, `rule_id`, `user_id`, `goal_id` (composite FKs `(rule_id, user_id)` → rules CASCADE and `(goal_id, user_id)` → `goals(id, user_id)` RESTRICT), `amount_or_cap NUMERIC(12,2) NULL`, `position`; `UNIQUE (rule_id, goal_id)`. `position` is UI order, never financial priority |
| `rule_executions` (E6) | `id`, `user_id`, `rule_id` (composite FK RESTRICT), `rule_version`, parameter snapshot, `source_type`, `source_id` (**soft reference**: Income CRUD is never blocked and history survives deletion), `triggering_event_id`, source snapshot, capacity snapshot (`reservable`, `floor`, `holds`), `status` (`awaiting_confirmation`/`executed`/`executed_partial`/`skipped`/`blocked`/`rejected`/`expired`/`cancelled`), `reason_code`, `hold_sequence BIGINT NULL` (sequence, assigned once at proposal creation, never changed), `expires_at NULL` (immutable proposal expiry), `decided_at`, timestamps; `UNIQUE(user_id, rule_id, source_type, source_id)` (version deliberately not in the key); `uq(id, user_id)`; CHECK `hold_sequence IS NULL ⇔ expires_at IS NULL` (not tied to the current status) |
| `rule_execution_items` (E6) | `id`, `user_id`, `execution_id`, `goal_id`, `account_id`, `position`, `planned_amount`, `applied_amount NULL`, `goal_transaction_id UUID NULL UNIQUE` → the real GoalTransaction; ownership FKs for execution, Goal and Account |
| `rule_execution_audit` (E6) | `id`, `execution_id`, `user_id`, `code`, `actor` (system/user), `related_event_id`, `details` (codes), `created_at`; append-only |
| `rule_alerts` (**E9A, not E4**) | physical schema finalized in E9A (P85). Required semantics: `user_id`, `rule_id`, `subject_type`, `subject_id`, `period_key`, `level`, `created_at`, `acknowledged_at`; unique per alert transition / level so a Budget level is alerted once per period and only escalations re-alert |
| `goal_transactions.rule_execution_id` (E6) | §19.2 |
| `budgets` (E4) | add `UNIQUE (id, user_id)` (FK target for BUDGET_ALERT) |

### 19.4 Migration principles

Before any constraint migration: a **read-only production verification**, with
explicit authorization, of valid currency codes, valid statuses and
goal-owner = transaction-owner. A mismatch is a data incident: stop. Then
backup, migration plan and approval (G3). The only data operation is the
`currency` copy. Applied migrations are never rewritten.

**VF-020E migration policy (APPROVED P86).** Several migrations aligned with the runtime
stages (E2, E4, E6, and E9A if schema is required); never one giant E migration. Every
schema stage passes the same production gate sequence: explicit production authorization →
read-only preflight → backup → backup verification → `SET LOCAL lock_timeout` →
exact-revision migration → post-verification; never a generic `upgrade head` against
production. No E contract migration is planned; one is added only if a real temporary-expand
invariant needs tightening after runtime deployment.

---

## 20. API Contracts (Goals / Accounts implemented through VF-020D; Rules contract for VF-020E)

### 20.1 Goals

- `POST /api/v1/goals/{id}/transactions` (VF-020C2): `type`, `amount`,
  `description?`, `account_id?`, `effective_date?`, `client_request_id?`.
  `account_id` omitted/null = tracked partition; `account_id = A` = linked
  partition of Account A, for a contribution **and** for a withdrawal/release
  (P64). Evaluation order: validation → **occupied key resolved first (200
  replay / 409 conflict, with no date or lifecycle check)** → new-request checks.
  New-request rules: tracked - B3 semantics (past/today ok, future 422); linked -
  `client_request_id` mandatory and `effective_date` omitted or equal to server
  today (P58).
  - **201** created; **200** replay (the original transaction, original
    `effective_date`).
  - **404** Goal missing or not owned; Account missing or not owned (linked).
  - **409** idempotency conflict (different payload, a different `account_id`,
    or a linked original retried without `account_id`); archived Goal
    (contribution); archived Account (linked contribution); amount above the
    selected partition's balance; amount above `reservable_amount` or
    `reservable_amount ≤ 0` (linked contribution).
  - **422** currency mismatch between Goal and Account; future `effective_date`
    (tracked); `effective_date ≠ today` (linked); missing
    `client_request_id` (linked); malformed fields.
  - Request example (linked reservation): `{"type":"contribution",
    "amount":"250.00","account_id":"<account uuid>","client_request_id":"<uuid>"}`.
  - Response gains `account_id` (nullable) beside `currency`, `effective_date`
    and `client_request_id`.
  - No floor warning field in VF-020C (P60). From VF-020E5 the **POST** response adds the additive `warnings` list of §10.6 (P79); the `GET` schema is unchanged.
- `GET /api/v1/goals`, `PATCH /api/v1/goals/{id}` (VF-020C2): `current_amount`
  unchanged (total) + `tracked_amount`, `linked_amount`, `allocations[]` (P63).
  `allocations[]` is the current non-zero partition summary, not an audit
  history (§7.2). Further additions: `priority_rank` (VF-020D) and
  `monthly_contribution_estimate` (backend-computed, ROUND_UP 0.01, PROPOSED).
- `PUT /api/v1/goals/priorities` (VF-020D, §9, P73): body `{"goal_ids": [...]}`,
  the complete ordered non-archived set; 200 with the canonical Goal list.
  `GoalCreate` and `GoalUpdate` never accept `priority_rank` (P74).

### 20.2 Idempotency transition (P14 APPROVED; cutover timing P59 PROPOSED)

1. VF-020B (implemented): `client_request_id` optional for tracked operations
   (requests without a key behave as today, **without** an exactly-once
   guarantee); the updated mobile client always sends it. VF-020C2: **required
   for every linked operation**, contribution and withdrawal/release alike
   (422 without it; also enforced by a database CHECK, §19.2). The canonical
   payload compared on replay is `goal_id`, `type`, `amount` (Decimal),
   `description`, `account_id` and, only when the replay states one,
   `effective_date`; an omitted `account_id` on a retry of a linked transaction
   is a conflict, not "ignore" (P64).
2. After all supported clients send it: required for every operation (422
   without it), timing per P59.

### 20.3 Accounts

`GET /api/v1/accounts` (VF-020C2) adds exactly these fields, with the formulas
of §8.1: `balance_as_of_today`, `scheduled_outflows`,
`planned_transfer_outflows`, `reserved_amount`, `unallocated_amount`,
`reservable_amount` (signed), `allocation_status` ∈ {`normal`, `overcommitted`}
and `negative_balance`. `current_balance` is unchanged and keeps its meaning.
`proposal_holds_amount` and any floor field are **not** part of VF-020C; they
arrive with VF-020E (P60, P62), staged without querying tables before their
production schema exists (P86): **E5** adds `minimum_unallocated_floor` (from
`financial_rules`, available after the E4 schema); **E7** adds `active_rule_holds` and
`rule_capacity` (from `rule_executions`, after the E6 schema). All are additive.
`confirm_capacity` depends on proposal X and is **not** an `AccountResponse` field: it
appears only in the proposal read model. The figures are computed with a bounded number
of grouped queries for all of the user's Accounts (no per-Account queries).
Deleting an Account or changing its currency returns the controlled 409 of
§8.3 (P65).

### 20.4 Rules

- `POST/GET/PATCH/DELETE /api/v1/financial-rules`;
  `POST /api/v1/financial-rules/{id}/enable|pause|disable`.
- `POST /api/v1/financial-rules/{id}/preview`: dry run, writes nothing.
- `POST /api/v1/financial-rules/evaluate`: drains **only the caller's** due
  events (bounded) and evaluates alerts; idempotent; returns a summary; never
  scans historical Income.
- `GET /api/v1/rule-proposals`, `POST /api/v1/rule-proposals/{id}/confirm`,
  `POST /api/v1/rule-proposals/{id}/reject`.
- `GET /api/v1/rule-executions` (items and audit, paginated).
- `GET /api/v1/rule-alerts`, `POST /api/v1/rule-alerts/{id}/acknowledge`.
- A proposal read model exposes `planned_amount`, `hold_sequence`, `expires_at`,
  `status` and, for display, `confirm_capacity`.
- **Staged availability (APPROVED P86).** E5: rule CRUD exists, floor rules may be
  enabled, allocation rules may be created and edited as drafts only; AUTO / CONFIRM
  execution is **not** active. E7: AUTO execution, best-effort and user drain become
  available; unattended copy stays prohibited until P50 is verified and enabled (E10).
  E8: CONFIRM enable, proposals, confirm, reject and expiry become available.
- Confirm / reject of a terminal execution is idempotent: it returns the stored state
  with no second financial effect. Confirm that finds `confirm_capacity < Σ planned`
  returns 409 and the execution becomes `cancelled (stale)`.

### 20.5 Dispatcher

No public cross-user endpoint. The periodic dispatcher (P50) runs as a backend
module invoked by the verified scheduled mechanism.

### 20.6 Conventions

Bearer JWT; 401 unauthenticated; 404 for a missing or foreign resource
(indistinguishable); 409 lifecycle, state or capacity conflict; 422 malformed or
invalid input; 201 on create; decimals as strings; pagination; bounded queries.

---

## 21. Mobile UX (VF-020 v1)

**All mobile rule, proposal, Inbox and floor-warning work belongs to VF-020F; VF-020E is
backend / schema / dispatcher only (APPROVED P86).** Expo SDK 57; everything works in **Expo Go**; no new native dependencies.

- **Goals:** rank, progress, tracked/linked amounts, deadline, monthly estimate, rule badges.
- **Goal detail:** history by partition; contribute and release with partition
  selection (existing `account-picker.tsx`); reorder (VF-020D). The floor
  warning on manual reservations is delivered by the backend in VF-020E (P60, P79); its
  mobile UX belongs to VF-020F. For a
  linked operation the app always sends `client_request_id`, never sends
  `effective_date`, and reuses its stable-attempt key on retry (VF-020C3).
- **Accounts:** recorded balance, balance as of today, reserved, unallocated,
  reservable, overcommitted / scheduled-shortfall badges.
- **Rules:** create, preview, AUTO/CONFIRM, enable/pause, history, failures.
- **Inbox:** proposals with their expiry (confirm/reject with revalidation
  messages), alerts, results, `dead` events.
- **Drain:** `POST /api/v1/financial-rules/evaluate` on `AppState` → active and
  when the Inbox opens; on reported changes, invalidate the families below.
- **Texts:** "Tracked (not linked to an account)" vs "Reserved in <Account>";
  "Unallocated" is never presented as money guaranteed to be available at the
  bank. Without the periodic dispatcher, AUTO copy says rules run "after you
  record income, or the next time you open the app".

| After | Invalidate |
|---|---|
| tracked goal transaction | `["goals",uid]`, `["goals","transactions",uid,id]`, `["analytics","goal-progress",uid]` |
| linked goal transaction | the above + `["accounts",uid]` |
| priority reorder | `["goals",uid]`, `["financial-rules",uid]` |
| rule changes | `["financial-rules",uid]`, `["rule-proposals",uid]`, `["accounts",uid]` (holds) |
| confirm / reject / drain with changes | `["rule-proposals",uid]`, `["rule-executions",uid]`, `["rule-alerts",uid]` + linked-transaction families |
| Income create/update/delete | existing families + `["accounts",uid]` + rule families |
| Expense / Transfer (incl. planned) / adjustment | existing families + `["accounts",uid]` + `["rule-alerts",uid]` |

Financial Overview is **not** invalidated by reservations or holds. Not in v1:
push notifications, scheduled rules, wallets, bank redirects (§22.2).

---

## 22. VF-021 Connections and Import (separate milestone)

Independent of the VF-020 sequence; discovery may proceed in parallel; no
integration code before G2 and G5.

### 22.1 Consent and connections (EXT)

Disclosure: provider, institution, data categories, accounts, purpose,
retention, expiry, disconnect. Consent record: `user_id`, provider, external
reference, scope, sources, `authorized_at`, expiry, state, revocation, policy
version; credentials stored separately and encrypted. States: `initiated`,
`authorization_pending`, `active`, `reauthorization_required`,
`temporarily_unavailable`, `revoked`, `expired`, `failed`; a revoked connection
fetches nothing. Read-only access initially; provider-approved flows; PKCE,
state/nonce; verified webhooks; least privilege. Regulation (P20): AISP model
or regulated partner, PSD2 and national rules, GDPR basis, processor
agreements, cross-border processing, DPIA.

### 22.2 Platforms (P22, EXT)

No universal Apple Wallet or Google Wallet transaction access is claimed.
FinanceKit requires an entitlement, an eligible region and a development build
(not Expo Go). Google Pay is not a purchase-history source. Payment apps each
need their own assessment. Production bank redirects need a unique app scheme
or universal links. No scraping, private APIs or credential collection.

### 22.3 Account mapping and balances

`ExternalAccountMapping` to an existing internal Account; never a silent merge;
exact currency match. A provider balance is an observation with a difference
and a status (P26); no synthetic adjustments.

### 22.4 Pipeline

Fetch → minimized evidence → normalize → deduplicate → reconcile → classify →
canonical posting (P23) → ledger → analytics invalidation → `financial_events`
with provenance (§16) → rules → audit.

### 22.5 Reconciliation

| Pair | Outcome |
|---|---|
| Manual record ↔ import | candidate match; review when ambiguous; user data preserved; counted once |
| Receipt-confirmed Expense ↔ import | link to the existing Expense |
| Pending ↔ booked (different id and amount) | one economic event; a correction, not a new record |
| Reconnect / overlapping sync | stable references → no new records; fallback → review |
| Two owned legs | one AccountTransfer (same currency); never Income + Expense |
| One owned leg | review |
| Several providers for one account | one mapping; conflict → review |

REC-1: one economic event ↔ at most one canonical record. REC-2: an imported
event links to at most one canonical record. REC-3: a canonical record may have
several pieces of evidence. REC-4: user annotations are never overwritten
without a defined rule.

### 22.6 Unsupported instruments (P38, P39)

Card liabilities and card FX settlement are research topics; such events stay in
`requires_review`. Synthetic Income or Expense is **never** created for
unmodeled activity.

### 22.7 Synchronization and completeness

Backfill, cursors, pagination, overlapping windows, duplicates, rate limits;
at-least-once delivery with idempotent processing. Visible: last sync, missing
accounts, unmatched and failed events, staleness. `AUTO` is blocked while
required data is incomplete (P32).

### 22.8 Disconnect and retention

Disconnect stops retrieval, revokes the token, disables credentials and cancels
syncs. Retention of imported data: P27 (EXT). Manual data is never deleted.
**The previously incomplete secret rotation must be finished before storing
third-party banking tokens.** Every new table follows the Data API privilege
restrictions.

---

## 23. Security, Privacy and Regulatory Gates

| Gate | Condition |
|---|---|
| G1 Financial contract | approved decisions recorded (this document) |
| G2 Provider and regulatory (VF-021) | legal review: access model, PSD2, GDPR, agreements, retention |
| G3 Database safety | migration plan, **read-only production verification**, backup, explicit approval |
| G4 Integration verification | deterministic allocation, outbox, concurrency and reconciliation tests green |
| G5 Security review | auth, ownership, L0/locks, tokens, logs, audit, Data API REVOKE on every new table; secret rotation finished before VF-021 |
| G6 Device acceptance | real-device verification, not static checks |
| G7 Publication | independent review, PR, CI; the user performs the merge |

Additionally: rules never run user code; `evaluate` is rate-limited per user;
logs and `outcome_summary` contain no amounts or personal data; ownership tests
use a foreign-user positive control.

---

## 24. Financial Scenario Matrix

Setup unless stated: today 2026-10-10; CHK (EUR) opening 2,000.00 dated
2026-10-01; G1/G2/G3 in EUR with ranks 1/2/3. B = balance as of today,
R = reserved, U = unallocated, RS = reservable.

| # | Scenario | Result | Refs |
|---|---|---|---|
| S1 | Reserve 500 for G1 on CHK | B 2,000; R 500; U 1,500; RS 1,500; no AccountTransaction; Overview unchanged | P02, FIN-004 |
| S2 | G1: 300 tracked + 500 linked | G1 total 800; assets 2,000 | FIN-002 |
| S3 | G1 500 + G2 800 | R 1,300; U 700 | — |
| S4 | Release 200 from G1 (after S3) | R 1,100; U 900; B 2,000 | P07, FIN-004 |
| S5 | Reserve 800 when RS = 700 | 409; nothing changes | P04 |
| S6 | G1 300 tracked + 500 linked; withdraw 400 from tracked | 409; withdraw 400 from linked(CHK): OK, linked 100 | P07 |
| S7 | (after S1) linked Income 1,000 dated 10-15 | current 3,000; B 2,000; RS 1,500 (future credit adds nothing); reserving 1,800 → 409; the Income's event is deferred to 10-15 | P36, §12 |
| S8 | (after S1) linked Expense 1,200 dated 10-20 | current 800; B 2,000; U 1,500; scheduled 1,200; RS 300 | P36 |
| S9 | (after S3) Expense 1,000 today | B 1,000; U −300 → overcommitted; Goals unchanged; Overview +1,000; Expense **not** blocked | P05 |
| S10 | (after S1) posted Transfer CHK→SAV 1,800 | CHK B 200; U −300 overcommitted; SAV +1,800 | P05, INV-08 |
| S11 | Goal in USD, CHK in EUR | linked → 422; tracked allowed | P06 |
| S12 | CHK archived, R 500 | new reservation → 409; release 200 → R 300; delete → 409 | P09 |
| S13 | SAV: only a linked Income 1,000; reserve 600; Income deleted | SAV B 0; R 600; U −600; delete SAV → **409**, not 500 | §8.3 |
| S14 | RS 1,000; G1 700 and G2 600 concurrently | serialized: first OK, second 409; replay of the same key → 200 | P04, P14 |
| S15 | Legacy: opening 1,000 + contribution 200 | tracked 1,200; withdrawal 150 without account → 1,050 | P12 |
| S16 | Rule example A (§10.7), AUTO | G1 300 / G2 200 / G3 100; R 1,100; U 3,900 | P44, P48 |
| S17 | Rule example A, CONFIRM | proposal 300/200/100 with a hold of 600; nothing written until confirmed | P01, P55 |
| S18 | (VF-020E; needs the floor, P60) Rule example B (floor 4,200) | `skipped`; with `allow_partial`: G1 300 | P29, P56 |
| S19 | Rule example C (7 % of 3,333.33) | 233.33; remainder unallocated | P44, P45 |
| S20 | After S16: salary 3,000 → 2,000 | reservations unchanged; B 4,000; U 2,900; `source_changed`; alert | P47 |
| S21 | After S16: salary deleted | B 2,000; R 1,100; U 900 < floor 1,000 → floor alert (not overcommitted); `source_deleted` | P47 |
| S22 | After S16: salary moved to SAV | CHK B 2,000, U 900; SAV +3,000; reservations stay on CHK | P47 |
| S23 | Rule active since 10-05 (`effective_from` 10-05); on 10-10 a salary dated 10-07 is entered | manual/live (10-07 ≥ 10-03), E5 ✓ → eligible. A salary dated 09-28 → manual/historical, E5 ✗ | P46, P51 |
| S24 | Same Income event processed twice | one execution; replay | §13 |
| S25 | RS 600; R1 500 (order 1), R2 400 (order 2), FIXED | R1 500; R2 `skipped`; with partial on R2: 100 | P29, P48 |
| S26 | CONFIRM proposal 600 → Expense 4,000 → confirm | B 1,000; R 500; U 500; `confirm_capacity` = 500 − 1,000 (floor) − 0 = −500 → 409; `cancelled (stale)`; no writes | §11 |
| S27 | Contribution to an archived Goal | 409 for tracked (implemented in VF-020B1) and, from VF-020C2, for linked contributions | P10 |
| S28 | Income commits; the API crashes before dispatch | event stays `pending`; processed at the next drain or by the periodic dispatcher; one execution; no invented money | F1 |
| S29 | Crash in AUTO after staging writes for three targets | rollback: no goal rows, no execution row; lease expires → retry → exactly one set of rows; nothing partial presented as success | F1, F2 |
| S30 | The same event delivered three times | one financial effect; one execution id; replays visible in the outcome | F2 |
| S31 | Two rules compete for 600 concurrently (§14.3) | R1 500, R2 skipped, on every run | F3 |
| S32 | (VF-021) rule enabled 10-01; bank connected 10-10; a 10-08 transaction arrives in backfill | Income created and counted in Overview; provenance import/historical → **no AUTO** | F4, P46 |
| S33 | (VF-021) pending P1 50.00 → booked B1 48.50 | one canonical record (correction); no duplicate record; no second execution | F4, REC-1 |
| S34 | Income deleted after an executed allocation | reservation unchanged; `source_deleted`; capacity recomputed; warning; no compensation | P47 |
| S35 | Proposal created with capacity; an Expense then reduces it | confirmation revalidates → 409, `cancelled (stale)`; no partial writes | §11 |
| S36 | (after S1) planned Transfer CHK→SAV 800, `planned_date` 10-20 | no ledger rows: current 2,000; B 2,000; U 1,500; planned out 800; **RS 700**; SAV RS unchanged (planned incoming ignored). After posting on 10-20: CHK B 1,200, planned out 0, U 700, RS 700 (no double subtraction) | P49 |
| S37 | AUTO active since 10-01; on 10-10 a salary dated 09-20 is entered | manual/historical (09-20 < 10-03) and E5 ✗ → no execution; Income recorded normally and counted in Overview | P46, P51 |
| S38 | RS 600, floor 0; one event: R1 (order 1, CONFIRM) FIXED G1 500, R2 (order 2, AUTO) FIXED G3 400 | proposal X with hold 500; R2 sees `rule_capacity` 100 → `skipped`. Confirm X: `confirm_capacity` = 600 − 0 − 0 (own hold excluded; no prior holds) = 600 ≥ 500 → executed; R 500; hold ended | P55, P48 |
| S39 | As S38 before confirmation; the user manually reserves 300 for G2 | allowed (holds do not block manual): RS 300. Confirm X: `confirm_capacity` = 300 − 0 − 0 = 300 < 500 → 409, `cancelled (stale)`; nothing written | P55 |
| S40 | (VF-020E; needs the floor, P60. In VF-020C only the 409 half applies: 800 → allowed without any warning, 1,600 → 409) RS 1,500, floor 1,000; manual reservations | 800 → allowed with a floor warning (RS 700 < floor); 1,600 → 409 (exceeds reservable; the floor override never creates money) | P56, P04 |
| S41 | Proposal created 10-10, expires 10-17; confirm on 10-18 | `expired` returned; no GoalTransaction; the hold stopped counting at 10-17 | P54 |
| S42 | Manual Income created 10-10 | `received_at` 10-03 → manual/live (inclusive boundary); 10-02 → manual/historical | P51 |
| S43 | Income committed; after-response task lost; user inactive for 3 days | without the periodic dispatcher: AUTO runs at the next drain, against capacity at that time; with it: within the configured cadence (target ≈ 10 min) | P50 |
| S44 | RS 600, floor 0; one event: R1 (order 1, CONFIRM) FIXED G1 500 → X; R2 (order 2, CONFIRM) FIXED G3 100 → Y (`rule_capacity` 600 − 500 = 100); then an Expense 80 today → RS 520 | Confirm X: `confirm_capacity` = 520 − 0 − 0 (Y is ordered after X and does not count) = 520 ≥ 500 → executed. Confirm Y: RS 20 (X now reserved), prior holds 0 → 20 < 100 → `cancelled (stale)`. Counting Y's later hold against X would have given 420 < 500 and wrongly defeated the higher-priority X | P55, P48 |
| S45 | Linked contribution, `effective_date` omitted, on day D; retry with the same key and payload on D+1 | 200; original transaction with `effective_date = D`; no second row | P58, P14 |
| S46 | Linked contribution or withdrawal with `effective_date` = yesterday, or tomorrow, and a new key | 422 for both; nothing written. A tracked contribution dated yesterday → 201; tomorrow → 422 | P58 |
| S47 | Linked contribution key K on CHK; retry K on SAV, and retry K without `account_id` | 409 for both; one row | P64, P14 |
| S48 | Goal with 300 tracked + 500 linked(CHK); withdrawal 400 without `account_id` | 409 naming the partition (total 800 would cover it); withdrawal 400 with `account_id = CHK` → linked 100 | P64 |
| S49 | Goal history linked to CHK, all released (linked net 0); delete CHK, or change its currency | 409 for both: the historical reference counts | P65 |
| S50 | `allocations[]` of the Goal in S48 after the 400 release from CHK | one entry (CHK, 100.00); a fully released partition is not listed; the list is not a history | P63 |

---

## 25. Test and Acceptance Strategy

All tests run only against the verified `valor_test` database. Expected values
are independent literals, never copies of production formulas.

| Area | Tests |
|---|---|
| Decimal | ROUND_DOWN allocations; remainders; percentage on `Income.amount` vs `base_amount` (P44); no float |
| Partitions | each partition ≥ 0; §7.2 formulas; legacy totals identical |
| Ownership | foreign Goal/Account/rule/proposal → 404; composite FKs reject cross-user rows |
| Currency | 422 for linked reservations; composite FK |
| Idempotency | goal keys (replay / conflict); executions; repeated confirm |
| Rollback | fault injection in AUTO and in confirmation |
| Outbox | Income + event atomic; Income rollback → no event; deferral by `not_before` |
| Replay / crash | S28–S30; lease expiry; attempts and backoff; `dead` |
| Periodic dispatcher | readiness checks for the chosen mechanism; cross-user batches; bounded queries (S43) |
| Concurrency | CT-01 S31 with two workers (repeat N times); CT-02 S31 + concurrent manual reservation; CT-03 two events of one user (FIFO, no duplicates); CT-04 confirmation vs dispatcher; CT-05 Income update vs processing of the same Income; CT-06 Expense/Transfer vs reservation; CT-07 Account delete / currency change vs reservation (409 or success, never 500); CT-08 reorder vs dispatcher; CT-09 rule edit vs dispatcher (no surviving old-version proposal); CT-10 two users in parallel; CT-11 manual reservation vs confirmation (S39); CT-12 planned Transfer create/post vs reservation |
| Priority | S25/S31 deterministic; reorder |
| Priority - schema/backfill (VF-020D) | active and completed ranked; archived NULL; newest-first preserved (`created_at DESC, id ASC`); deterministic id tie on equal `created_at`; several users independent; `priority_rank >= 1` CHECK; deferred uniqueness (a swap inside one transaction succeeds, a committed duplicate fails); D5 normalizes rollout stragglers (appended after the user's max by `created_at ASC, id ASC`) before the lifecycle CHECK |
| Priority - L0 (VF-020D) | deterministic key derivation (§14.5); same UUID same key; different UUIDs normally different keys; released after commit and after rollback; every Goal write path takes it (create, PATCH, DELETE, tracked and linked contribution/withdrawal, reorder); read-only requests do not; an occupied-key replay does not enter the write path; Account delete and currency change do not take it |
| Priority - CRUD (VF-020D) | create non-archived appended last; create archived NULL; archive NULL without compaction; reactivate appended last; active ↔ completed keeps rank; non-status edit keeps rank; delete leaves a gap; `GoalCreate`/`GoalUpdate` reject `priority_rank` |
| Priority - reorder (VF-020D) | valid reorder; same-order idempotence; duplicate id → 422; malformed UUID → 422; missing ranked Goal → 409; archived supplied → 409; foreign and nonexistent → indistinguishable 404; empty with zero ranked → 200; empty with ranked → 409; response is the canonical full list including archived; ranks rewritten `1..n` |
| Priority - concurrency (VF-020D) | reorder vs reorder, create, archive, reactivate, delete, tracked contribution, tracked withdrawal, linked contribution, linked withdrawal; create vs create; reactivate vs create; different users proceed independently (apart from a theoretical hash collision); no deadlock |
| Priority - regression (VF-020D) | B3 idempotency; C2 linked capacity and lifecycle protections; archived-Goal restrictions; completed-Goal money semantics |
| Priority - mobile (VF-020D) | draft move up/down and boundaries; unchanged draft keeps Save disabled; Save pending state; lifecycle filtering (active and completed only); stale-set 409 resets and refetches; cache replacement from the response; no new test framework |
| Income CRUD | every row of §15.3 |
| Event atomicity (E3) | no-account create, linked create, update, delete each write the event in the same transaction; a forced failure rolls back both; `commit=False` callers keep both uncommitted; no event for a failed write |
| Rule DELETE (E5 / E7) | **E5:** deleting a draft / non-executed rule succeeds when otherwise allowed; no query of `rule_executions`. **E7:** a rule with an `executed`, `executed_partial`, `skipped` or `blocked` execution (and, when it exists, a proposal / `awaiting_confirmation` execution) → DELETE 409; foreign or nonexistent rule → indistinguishable 404; no raw FK `IntegrityError` / 500; a regression proves the pre-check runs before the FK backstop |
| Floor and holds (E5/E8) | one floor rule per Account; disabled floor = 0; manual warning only when `projected_reservable < floor` and never because of holds; E5 warning shape has no `projected_rule_capacity`, from E7 it is the additive `projected_reservable − floor − active_rule_holds`; replay recomputes `warnings`; `hold_sequence` immutable and retained after terminalization; S44 |
| Rule-generated rows (E6/E7) | the three new CHECKs; item → GoalTransaction link UNIQUE; no `client_request_id` on rule rows; legacy rows valid |
| Provenance | S23, S32, S33, S37, S42; reclassification; Income without a creation event |
| Proposals | expiry (S41), stale (S26/S35/S39), superseded, source_changed; holds: `rule_capacity` for AUTO and new proposals, `confirm_capacity` excluding the own hold (S38), later holds never defeating an earlier proposal (S44); hold order deterministic for the chosen mechanism |
| Dispatcher FIFO (P52) | head selected before the claimable predicate; a newer event is never selected while the head is `processing` with a live lease or `failed_retryable` waiting; `claim_token` verified; expired lease reclaim increments `attempts` while `attempts < 6`; a `processing` head with an expired lease and `attempts = 6` becomes `dead` (`lease_expired_max_attempts`, lease and `next_attempt_at` cleared, no seventh claim, CHECK never violated) and then no longer blocks newer events; sixth failure → `dead`; delays 1 m / 5 m / 30 m / 2 h / 12 h; manual re-queue `dead → pending` resets `attempts`, `next_attempt_at`, `lease_expires_at`, `claim_token`, `last_error_code`, `processed_at`, keeps identity / snapshot / provenance / `occurred_at` / `not_before`, and creates no execution; an older `failed_retryable` event waiting for backoff blocks newer events of the same user; an event deferred by a future `not_before` does not; after `dead`, newer events proceed |
| Capacity | future credits/debits (S7/S8); planned Transfers (S36) incl. no double subtraction after posting; date rollover; exact boundary `amount = reservable_amount` OK, `reservable_amount ≤ 0` → 409; negative `reservable_amount` returned signed; `allocation_status` / `negative_balance` (S9/S10); floor strict for rules, warning for manual (S18/S40: VF-020E, P60) |
| Linked dates and keys (P58) | linked contribution and withdrawal: key mandatory (422, plus the database CHECK); omitted date = today; explicit past/future → 422; tracked semantics unchanged; occupied-key replay on a later day → 200 (S45/S46) |
| Partitions (P63/P64) | withdrawal without `account_id` against tracked only (S48); linked withdrawal from the named partition; multiple Accounts; `allocations[]` shows only non-zero current partitions (S50); `current_amount = tracked_amount + linked_amount`; legacy Goals unchanged |
| Idempotency with `account_id` | same key + different or omitted `account_id` → 409; replay after archiving the Goal or the Account → 200 (S47) |
| Lifecycle | archived Goal (P10, tracked and linked), archived Account (S12), completed Goal unchanged, delete or currency change with historical linked references including net-zero history (S13, S49) |
| Database (C1) | FK rejects wrong currency, wrong user and unknown Account; the three CHECKs; `ON DELETE RESTRICT`; legacy rows NULL; real Alembic upgrade/downgrade on throwaway `*_test` databases (B4 pattern); B4 application code against the C1 schema |
| Budgets | transitions, deduplication, no duplicated limits |
| No double counting / Overview | Overview unchanged by reservations and holds; Goal totals not counted as assets |
| API compatibility | existing goal tests; additive fields |
| Database permissions | Data API REVOKE on every new table |
| Mobile | typecheck/lint; invalidation per §21; device acceptance (G6) |

Acceptance: gates G1–G7, full backend regression, CI green, documentation
matching the implemented state, the user performs the merge.

---

## 26. Decision Register P01–P48

| ID | Decision | Status |
|---|---|---|
| P01 | AUTO + CONFIRM, internal only | **APPROVED** |
| P02 | Model B + C | **APPROVED** |
| P03 | Per-transaction linking | **APPROVED** |
| P04 | 409 above capacity | **APPROVED** |
| P05 | Spending not blocked; overcommitted shown | **APPROVED** |
| P06 | Exact currency match | **APPROVED** |
| P07 | Explicit partition, each ≥ 0 | **APPROVED** |
| P08 | Reservation move = release + reserve; atomic move deferred | PROPOSED |
| P09 | Archived Account rules | **APPROVED** |
| P10 | Archived Goal rules | **APPROVED** |
| P11 | Completed Goal rules | **APPROVED** |
| P12 | Legacy history unchanged | **APPROVED** (also EST) |
| P13 | `effective_date` | **APPROVED** (refinement P58 APPROVED 2026-10-07: tracked vs linked rules) |
| P14 | Idempotency + transition | **APPROVED** (cutover timing P59 PROPOSED) |
| P15 | Terminology | **APPROVED** (`scheduled_shortfall` PROPOSED) |
| P16 | No external money movement | **APPROVED** |
| P17 | Expense → Goal attribution | PROPOSED (deferred) |
| P18 | Goals hardening first | **APPROVED** |
| P19 | Database integrity | **APPROVED** (no migration approved) |
| P20 | Open Banking access model | EXT |
| P21 | Provider / region | EXT |
| P22 | Wallets | EXT |
| P23 | Automatic import posting | UDR (VF-021) |
| P24 | Review of ambiguous imports | PROPOSED |
| P25 | Matching manual / receipt records | PROPOSED |
| P26 | Bank vs ledger balance | PROPOSED |
| P27 | Retention after disconnect | EXT |
| P28 | Rule order `execution_order`, `created_at`, `id`; duplicates and gaps allowed; no uniqueness | **APPROVED** (2026-10-16) |
| P29 | Partial allocation, default false | **APPROVED** |
| P30 | v1 timezone = server date | PROPOSED |
| P31 | One source Account per allocation rule; ownership FK `(source_account_id, user_id)`; no stored rule currency | **APPROVED** (2026-10-16) |
| P32 | AUTO blocked on incomplete data | PROPOSED |
| P33 | In-app notification defaults | PROPOSED |
| P34 | Reversal after a trigger change | **SUPERSEDED by P47** |
| P35 | Income eligibility | **APPROVED** |
| P36 | As-of capacity, conservative | **APPROVED** |
| P37 | Invalid enabled allocation rule → terminal `blocked` execution; no auto-pause | **APPROVED** (2026-10-16) |
| P38 | Liabilities outside VF-020 | PROPOSED / EXT research |
| P39 | Card FX settlement | EXT |
| P40 | Spending limits = Budgets | EST |
| P41 | User timezone | PROPOSED (deferred) |
| P42 | v1 triggers: `income.created`, `income.updated`, `income.deleted` through the outbox + drain | **APPROVED** (2026-10-16) |
| P43 | In-app channel | PROPOSED |
| P44 | Percentage basis = `Income.amount` | **APPROVED** |
| P45 | ROUND_DOWN | **APPROVED** |
| P46 | No retroactive execution | **APPROVED** |
| P47 | Corrections without reversal | **APPROVED** |
| P48 | Precedence | **APPROVED** |

---

## 27. Additional Decisions (P49+)

| ID | Decision | Content | Status |
|---|---|---|---|
| P49 | Planned Transfers in capacity | planned outgoing Transfers reduce `reservable`; planned incoming ignored; read model only; no ledger rows invented | **APPROVED** |
| P50 | Durable periodic dispatcher | required before unattended AUTO is presented as guaranteed; target cadence ≈ 10 min (5–15); boundary fixed by P87; **TECHNICAL VERIFICATION STILL REQUIRED** | **APPROVED** (mechanism: technical verification) |
| P51 | Live manual Income window | N = 7 days, inclusive; older manual entries historical; no override in v1 | **APPROVED** |
| P52 | Per-user FIFO with head-of-line blocking | order `occurred_at, id`; the head is selected among non-deferred unfinished events **before** the claimable predicate; a head `processing` with a live lease or `failed_retryable` waiting blocks the user; `processed`/`dead` never block; future `not_before` is outside head selection (§12.4) | **APPROVED** (2026-10-16) |
| P53 | Event retention | keep processed events as provenance until the user's data is deleted; no time-based cleanup in VF-020E; any later legal retention is external review (VF-021 / legal, EXT) | **APPROVED** for VF-020E technical behavior (2026-10-16); legal retention EXT |
| P54 | Proposal expiry | 7 days; lazy expiry | **APPROVED** |
| P55 | Soft capacity hold | holds reduce later rule capacity only; not reserved; never block real operations or manual reservations; full revalidation at confirmation | **APPROVED** |
| P56 | Floor for manual reservations | warning-only for manual, strict for rules; never overrides P04 or hard invariants (the floor itself: VF-020E, P60) | **APPROVED** |
| P57 | Lifecycle references | Goal delete / actual currency change referenced by a rule target → 409; Account delete / actual currency change referenced by a rule → 409; Goal and Account archive allowed (rules become invalid → `blocked`); rule delete only without executions; Budget delete referenced by a BUDGET_ALERT → 409; API pre-checks run before FK failure | **APPROVED** (2026-10-16) |
| P58 | `effective_date` of linked rows | tracked: B3 semantics (past/today ok, future 422); linked contribution **and** withdrawal/release: key mandatory, omitted = today, explicit must equal today else 422; occupied key resolved first | **APPROVED** (2026-10-07) |
| P59 | Mandatory `client_request_id` for all clients | after all supported clients send it | PROPOSED |
| P60 | Safety floor timing | deferred to VF-020E; no floor storage, field or warning in VF-020C | **APPROVED** (2026-10-07) |
| P61 | User advisory lock L0 | deferred to VF-020D/E; VF-020C uses Goal → Account row locks; **superseded by P68** | **APPROVED** (2026-10-07), superseded |
| P62 | Account read model | eight additive fields and exact formulas (§8.1, §20.3); `reservable_amount` signed; no holds/floor fields | **APPROVED** (2026-10-07) |
| P63 | Goal read model | `tracked_amount`, `linked_amount`, `allocations[]` = current non-zero partition summary, not an audit history | **APPROVED** (2026-10-07) |
| P64 | Partition selection and idempotency with `account_id` | explicit partition; no FIFO or auto-selection; archived Account/Goal rules; `account_id` in the canonical payload | **APPROVED** (2026-10-07) |
| P65 | Account lifecycle protection | delete / currency change → controlled 409 on any historical linked reference | **APPROVED** (2026-10-07) |
| P66 | Schema and rollout | nullable `account_id`, no allocations table, no provenance column; C1 → production migration → C2 → C3; no contract migration | **APPROVED** (2026-10-07) |
| P67 | Ranked Goals | all non-archived (active and completed) ranked; archived NULL | **APPROVED** (2026-10-13) |
| P68 | L0 introduced in VF-020D | every Goal write takes L0; Account delete / currency change do not; occupied-key replay does not | **APPROVED** (2026-10-13) |
| P69 | L0 key derivation | `pg_advisory_xact_lock(bigint)` from SHA-256 of the namespaced user UUID bytes | **APPROVED** (2026-10-13) |
| P70 | Rank gaps | no automatic compaction on archive or delete; reorder rewrites `1..n` | **APPROVED** (2026-10-13) |
| P71 | Backfill | `created_at DESC, id ASC` per user over non-archived Goals; archived NULL | **APPROVED** (2026-10-13) |
| P72 | Constraints | `>= 1` CHECK and deferrable `UNIQUE (user_id, priority_rank)` in D2; lifecycle CHECK only in D5 | **APPROVED** (2026-10-13) |
| P73 | Reorder API | `PUT /goals/priorities`, complete ordered `goal_ids`, 200 with the canonical Goal list | **APPROVED** (2026-10-13) |
| P74 | API exposure and order | read-only `priority_rank`; priority-aware `GET /goals`; archived `created_at DESC, id ASC` | **APPROVED** (2026-10-13) |
| P75 | Mobile priorities UX | Priorities screen, ▲ / ▼ + Save, no drag-and-drop dependency | **APPROVED** (2026-10-13) |
| P76 | Reorder idempotency and boundary | no key, no table; never writes money rows; ordering and lock foundation only | **APPROVED** (2026-10-13) |
| P77 | Rollout and production gates | D1 → D2 → gates → D3 → D4 → D5 | **APPROVED** (2026-10-13) |
| P78 | Floor as a rule | the floor is a `financial_rules` row of type `MINIMUM_UNALLOCATED_FLOOR`, exactly one per `(user, source Account)` (partial UNIQUE), `floor_amount NUMERIC(12,2) >= 0`, only `enabled` contributes, no mode / order / targets / executions; **not** an Account column | **APPROVED** (2026-10-16) |
| P79 | Manual floor warning | P04 unchanged; additive `warnings[]` on the POST response only when `projected_reservable < floor` (E5 shape: code, floor, `projected_reservable_amount`; `projected_rule_capacity` is additive from E7); holds never activate it; advisory, not persisted, outside the idempotency payload; replay recomputes it | **APPROVED** (2026-10-16) |
| P80 | Hold order | `hold_sequence BIGINT` from a PostgreSQL sequence, assigned once at proposal creation under L0, immutable; `prior_holds` uses `hold_sequence < X`; populated forever after terminalization; `created_at`/`id` are not the mechanism; S44 proof (§11.3) | **APPROVED** (2026-10-16) |
| P81 | Rule-generated GoalTransactions | `rule_execution_id` + composite FK; `client_request_id = NULL`; broadened linked-origin CHECK, mutual exclusivity, rule-row shape (§19.2); no fake client key; item → GoalTransaction link | **APPROVED** (2026-10-16) |
| P82 | Retry and claim constants | lease 5 min; `max_attempts = 6`; delays 1 m, 5 m, 30 m, 2 h, 12 h; no jitter; claim increments `attempts` and sets `claim_token`; an expired lease at `attempts >= 6` → `dead` (`lease_expired_max_attempts`), never a seventh attempt; manual re-queue `dead → pending` resets the retry cycle (§12.4); business results never retried; no committed `failed` execution | **APPROVED** (2026-10-16) |
| P83 | Typed outbox snapshot | `financial_events` keeps explicit typed provenance and snapshot columns; `aggregate_id` soft; Income gets no provenance column; atomic event write in the same transaction (§12.2) | **APPROVED** (2026-10-16) |
| P84 | Rule types and alert ownership | v1 types: `INCOME_ALLOCATION`, `MINIMUM_UNALLOCATED_FLOOR`, `OVERCOMMITMENT_ALERT`, `BUDGET_ALERT`; only allocation executes; `GOAL_DEADLINE_ALERT` deferred; `budgets UNIQUE (id, user_id)` + ownership FK; per-subject alert-rule uniqueness; one budget formula | **APPROVED** (2026-10-16) |
| P85 | Alert storage deferred | the physical `rule_alerts` schema is finalized in E9A, not E4 (dedup / transition semantics) | **APPROVED** (2026-10-16) |
| P86 | Staged E rollout | E1–E10 with several migrations, production gates and runtime-after-schema order; staged availability and Account fields; mobile belongs to VF-020F (§28) | **APPROVED** (2026-10-16) |
| P87 | P50 scheduled-process boundary | separate scheduled process (preferred: Render Cron Job) running a CLI entrypoint ≈ every 10 min; lifespan loop does not satisfy P50; `BackgroundTasks` best effort; authenticated evaluate = user drain; no public dispatcher endpoint; technical verification still required | **APPROVED** (2026-10-16) |
| P88 | Rule status machine and versioning | statuses `draft`/`enabled`/`paused`/`disabled`; transitions of §10.3; `active_since` reset on every enable; material vs non-material fields; `execution_order` non-material | **APPROVED** (2026-10-16) |

---

## 28. Dependency-Ordered Roadmap

### VF-020 Smart Goals & Rules

| Stage | Scope | Depends on |
|---|---|---|
| VF-020A Contract | this document; product-requirements and roadmap updates | — (complete when merged) |
| VF-020B Goals Hardening | G1–G6; P10; P13 column; P14 keys; composite owner FK; `currency` copy. **Implemented**: B1 app hardening, B2 expand, B3 runtime, B4 contract (production was at `8799b7fd923d` after B4; historical) | VF-020A; G3 (authorized read-only production check, migration approval) |
| VF-020C Goal Account Allocations | three sub-stages, strictly in this order (below): **C1** schema expand, **C2** backend runtime, **C3** mobile. Partitions; as-of model incl. P49; capacity; Account lifecycle pre-checks; API and minimal mobile surface. **No floor warning (P60), no L0 (P61)**. **Implemented**: C1 (`98acdc7016d2`), C2, C3 (historical stage description; L0 was introduced later by VF-020D) | VF-020B; G3, G4 |
| VF-020D Goal Priorities | rank, reorder and L0 on every Goal write (P67–P77). Stages: **D1** contract (this document), **D2** expand migration (nullable `priority_rank`, `>= 1` CHECK, deferrable unique, deterministic backfill; the runtime does not depend on the column before the production migration), then the production gates for D2 (explicit authorization → read-only preflight → backup → backup verification → short lock timeout → migration → post-migration verification), **D3** backend runtime (ORM/API, L0 helper on all Goal writes, lifecycle rank handling, canonical order, reorder endpoint, concurrency and regression tests), **D4** mobile priorities UI, **D5** contract migration (normalize stragglers appended after the user's max rank by `created_at ASC, id ASC`, then the lifecycle CHECK), which passes through the same seven-step production gate sequence as D2, then integration and acceptance. Every stage has its own strict review gate. **COMPLETE**: D1–D5 merged; D2 (`4d2f7b91a6c3`) and D5 (`7c1e5a9b3d28`) applied to production | VF-020C |
| VF-020E Rules Engine / Outbox / AUTO / CONFIRM | **Backend / schema / dispatcher only** (P86): floor as a rule (P78), outbox (P83), executions, AUTO, CONFIRM with holds (P55, P80), alerts, backend Inbox read model, periodic dispatcher (P50, P87). Stages E1–E10 below | VF-020D (complete); G4, G5 |
| VF-020F Mobile & Acceptance | **all** mobile rule management, proposal UI, Inbox UI, floor-warning UX, device acceptance, final mobile regression, documentation, independent review | VF-020E; G6, G7 |

#### VF-020E stages and rollout order (APPROVED P86)

Production migrations are manual while the backend auto-deploys on merge, so a runtime stage is never merged before the production schema it reads exists, and every schema stage is an expand that the previous runtime tolerates.

| Stage | Scope | Migration | Production gate | Runtime dependency / dependency proof |
|---|---|---|---|---|
| **E1** | contract and documentation only (this document and drift fixes) | no | no | none |
| **E2** | `financial_events` schema expand; strict migration review | yes | yes | old runtime ignores the new table; E3 requires E2 in production  **Status: COMPLETE, applied to production 2026-10-19 (`115998e2e795`).** |
| **E3** | Income outbox / provenance runtime: atomic create / update / delete event writes (§12.2); **no** allocation execution | no | no | requires E2 in production  **Status: COMPLETE, merged (PR #86).** |
| **E4** | `financial_rules` + `financial_rule_goal_targets` expand, `budgets UNIQUE (id, user_id)`, all four v1 rule types in the `rule_type` CHECK; **no** `rule_alerts` | yes | yes | old runtime ignores new tables and the added unique; E5 requires E4  **Status: COMPLETE, merged and applied to production 2026-10-21 (`861064d31463`).** |
| **E5** | rules CRUD, versioning, status, floor runtime, `minimum_unallocated_floor` on `AccountResponse`, manual floor warning, Goal / Account / Budget reference pre-checks; allocation rules stay non-executable drafts; rule DELETE without an execution-history pre-check (no executions can exist yet); the manual warning has the E5 shape (no `projected_rule_capacity`) | no | no | requires E4; **must not query `rule_executions` / `rule_execution_items` / holds** **Status: COMPLETE, merged (PR #88).** |
| **E6** | execution schema expand: `rule_executions`, `rule_execution_items`, `rule_execution_audit`, hold sequence, `goal_transactions.rule_execution_id`, evolved linked-origin CHECKs, item → GoalTransaction linkage | yes | yes | the replaced CHECK accepts every old row and write; the new RESTRICT FK `(rule_id, user_id)` → `financial_rules` is safe because the E5 runtime creates no executions; E7 requires E6  **Status: migration `e0503e9ca9d3` implemented on the local feature branch; not pushed, merged or applied to production.** |
| **E7** | outbox claim / process, P52 FIFO, AUTO executor, rule-generated GoalTransactions, best-effort drain, authenticated user drain, `active_rule_holds` + `rule_capacity` on `AccountResponse`; additive `projected_rule_capacity` in the manual warning; **rule DELETE `rule_executions` pre-check (controlled 409) in the same release that first creates executions**; no unattended claim | no | no | requires E6; concurrency tests CT |
| **E8** | CONFIRM: proposals, holds, 7-day expiry, confirm / reject, `prior_holds`, S44, `superseded` / `source_changed` / `source_deleted` / `rule_inactive` / `stale` | no | no | requires E7 |
| **E9A** | `rule_alerts` physical schema (floor, overcommitment, Budget transition / dedup) | yes (if required) | yes | old runtime ignores the table |
| **E9B** | alerts and the composed backend Inbox (no Inbox table); BUDGET_ALERT reuses the authoritative budget-status logic | no | no | requires E9A |
| **E10** | P50 scheduled-process technical verification and operationalization: Render capability, scheduled CLI, metrics, `dead`-event runbook, bounded batches, operational review | no (infra) | operational | requires E7; only after E10 may AUTO be presented as guaranteed unattended |

Each schema stage uses the production gate sequence of §19.4. Each stage has its own strict review gate. **No mobile work belongs to E.**

Each stage requires its own implementation authorization.

#### VF-020C sub-stages and rollout order (APPROVED P66; historical, fulfilled)

Production migrations are applied manually while the backend auto-deploys on
merge, so any code that reads a new column must not be deployed before the
migration. The order is therefore fixed:

| Step | Content | Gate |
|---|---|---|
| **C1** schema expand only | one Alembic revision after `8799b7fd923d` (§19.2): nullable `goal_transactions.account_id`, composite FK, three CHECKs, partial index; tests (real Alembic cycle, direct constraint behavior) and documentation. **`account_id` is not mapped in the ORM**, so the merged code runs unchanged against the B4 schema | strict review → push → PR → CI → user merge |
| **C1 production** | read-only production preflight → backup → execution-time lock policy → explicit migration authorization → read-only post-verification | each step separately authorized |
| **C2** backend runtime | only after C1 is applied to production: ORM mapping, linked contribution/withdrawal, capacity and partition checks, `account_id` in the idempotency comparison, Account and Goal read models, Account lifecycle pre-checks (P65) | strict review → push → PR → CI → user merge |
| **C3** mobile | Account selector, partition selector, tracked/linked display, overcommitted warning | typecheck, lint, helper tests, **physical-device acceptance** |

C1 production preflight requirements (read-only, aggregates and catalog
metadata only, no row-level data): production revision = `8799b7fd923d`;
`goal_transactions.account_id` absent; the four C1 constraint names and the
C1 index name absent; `uq_accounts_id_user_id_currency` present with exact
definition `UNIQUE (id, user_id, currency)`; row counts of `accounts`, `goals`
and `goal_transactions`; invalid Account/Goal currency or status counts;
GoalTransaction ownership and currency integrity (no mismatch, no orphan);
sessions and transactions (active, idle in transaction, long-running);
locks and lock waiters on `accounts` and `goal_transactions`; prepared
transactions; table and index sizes; Data API privileges of `anon`,
`authenticated`, `service_role` unchanged; the role's `lock_timeout` and
`statement_timeout`. Execution uses the separately authorized in-transaction
`SET LOCAL lock_timeout`.

No contract migration follows C3: `account_id` intentionally stays nullable
(NULL = tracked). Each step needs its own authorization; C2 may not start
before C1 is verified in production, and C3 may not start before C2 is merged.

### VF-021 Financial Connections & Import (separate strategic stream)

1. Provider and legal discovery (P20–P22, P27, P38, P39) — may run in parallel with VF-020.
2. Consent and connection architecture.
3. Provider adapters (sandbox).
4. Import normalization.
5. Reconciliation.
6. Canonical integration (P23–P26) and events with provenance.
7. Analytics and mobile.
8. Security and acceptance.

No integration code before G2 and G5.

### Documentation maintenance

- `docs/architecture.md`, `docs/api-contract.md`, `docs/database-schema.md`,
  `README.md` and the module list in `CLAUDE.md` change with each implemented
  stage, not with this contract.
- `docs/roadmap.md` kept "Goals are currently not connected to Accounts" until
  VF-020C2 shipped (historical rule, fulfilled: C2 is merged and deployed).
- `docs/modules/account-transfers.md` ("Transfers must not interact with
  Goals") stays valid: VF-020 involves no Transfer ↔ Goal movement; P49 only
  reads planned Transfers. Any future money-movement model requires a dated
  amendment preserving the original decision.
- `docs/modules/financial-overview.md` needs no change.
- `docs/modules/financial-connections.md` is created when VF-021 discovery starts.

---

## 29. Implementation Readiness and Release Gates

| Stage | Ready to plan | Release gates |
|---|---|---|
| VF-020A | complete with this document | review of the documentation diff |
| VF-020B | yes; needs an authorized read-only production check | G3, G4, G5, G7 |
| VF-020C | yes - contract finalized (v0.4); VF-020B is complete. C1 → production migration → C2 → C3 | G3, G4, G5, G6, G7 |
| VF-020D | **complete** (D1–D5; D5 applied to production as `7c1e5a9b3d28`, since superseded by `861064d31463`) | G4, G7 |
| VF-020E | contract finalized (v0.6); ready to start E2 after E1 review and merge; P50 mechanism verified in E10 | G4, G5, G6, G7; **GA of unattended AUTO only with the periodic dispatcher in place (E10)** |
| VF-020F | after VF-020E | G6, G7 |
| VF-021 | discovery yes; code no | G2 and G5 first |

"Ready to plan" is not implementation authorization.

---

## 30. Contract Self-Review

| Check | Result |
|---|---|
| Financial invariants consistent across §6–§8, §24 | PASS |
| One capacity model; no double subtraction of future debits and planned Transfers; posted Transfers counted only via ledger | PASS (§8.1, S36) |
| Planned incoming Transfers and future credits never add capacity | PASS |
| Goal and Account money never double-counted | PASS (FIN-002, §7.2, §7.5) |
| Soft hold never presented as a reservation | PASS (§8.1, §11.3) |
| Own hold not counted at confirmation; one definition of `confirm_capacity` | PASS (§8.1, §11.3, S38, S44) |
| Hold order is the approved `hold_sequence` mechanism (P80); never derived from the current status or from `created_at` | PASS (§11.3, §19.3) |
| FIFO and retry backoff consistent (P52, P82 APPROVED); head selected before the claimable predicate | PASS (§12.4, §14.4, §27) |
| Manual floor override cannot bypass P04 | PASS (§10.6, S40) |
| Historical Income cannot become AUTO-eligible | PASS (E4/E5/E6, §16, S32/S37/S42) |
| P50 not hard-coded to one hosting provider | PASS (§12.5) |
| AUTO unattended guarantee depends on a real periodic dispatcher | PASS (§11.1, §12.5, §29) |
| CONFIRM not presented as guaranteed execution | PASS (§11.2) |
| Scheduled rules, push, wallets, bank connections not presented as implemented | PASS (§5, §10.1, §21, §22) |
| No invented Income status; Budgets not duplicated | PASS |
| No contradiction with AccountTransfer semantics (planned = no ledger rows) | PASS (§8, INV-08) |
| No contradiction with Financial Overview semantics | PASS (FIN-012) |
| No unapproved decision labeled APPROVED (P59 PROPOSED; VF-021 UDR/EXT; P53 legal retention EXT) | PASS |
| VF-020C decisions P58, P60–P66 approved 2026-10-07 and consistently stated in §3, §7, §8, §10.6, §14.2, §18, §19.2, §20, §21, §24, §25, §27, §28; no floor, no `proposal_holds_amount`, no L0, no allocations table or provenance column in VF-020C (L0 is introduced by P68 in VF-020D) | PASS |
| Tracked vs linked `effective_date` semantics stated consistently (P58 is the normative text; §7.3, §7.4, §20.1, §25, S45/S46 repeat it without deviation) | PASS |
| `allocations[]` described as a current non-zero summary, never an audit history (§7.2, §20.1, S50) | PASS |
| Implementation state is represented consistently: VF-020C and VF-020D complete (D5 revision `7c1e5a9b3d28`); production schema at `861064d31463` (VF-020E2 and VF-020E4 applied); VF-020E3 merged (outbox writes, no processing); VF-020E4 schema applied to production; VF-020E5 rules CRUD and floor runtime merged (PR #88); VF-020E6 execution schema migration implemented on its local feature branch only (not applied to production); VF-020E rules, AUTO and CONFIRM not implemented; VF-020F not started | PASS |
| The floor is a `MINIMUM_UNALLOCATED_FLOOR` rule and nowhere an Account column (P78) | PASS (§10.6, §19.3) |
| No mobile implementation stage in VF-020E | PASS (§28) |
| `rule_alerts` physical schema deferred to E9A, not presented as migration-ready | PASS (§17, §19.3, P85) |
| No migration, production access or implementation authorized | PASS |
| Requirements traceable to tests | PASS (§24 ↔ §25) |
| Implementation sequence valid | PASS |

---

## 31. Readiness Verdict

1. **Contract status:** APPROVED FOR DOCUMENTATION / IMPLEMENTATION PLANNING. No
   user decision blocks the VF-020 product semantics.
2. **Approved decisions:** P01–P07, P09–P16, P18, P19, P28, P29, P31, P35, P36, P37,
   P42, P44–P57 (P53: technical retention), P58, P60–P88 (P34 superseded by P47; P61 superseded by P68).
3. **Remaining non-approved items:** PROPOSED technical refinements (P08, P17,
   P24–P26, P30, P32, P33, P41, P43, P59) finalized within their stages; P23 UDR
   for VF-021.
4. **External / legal gates:** P20, P21, P22, P27, P38 research, P39; G2 and G5
   for VF-021; finishing the secret rotation before storing banking tokens;
   technical verification of the periodic dispatcher mechanism (P50, E10), and any
   later legal retention requirement for events (P53).
5. **Implementation authorization:** not granted by this document. Each stage,
   each migration and any production-data access requires explicit approval.
