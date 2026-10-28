# MVP Design Handoff Index (VF-MVP-ENG-003)

Date: 2026-10-27. This is the entry point for UI/UX designers and the mobile lead. It points to the authoritative
documents and states, per surface, what is ready and what each surface depends on. It defines **no visual style**
(no colors, fonts, spacing); functional clarity first.

## 1. Reading order

| # | Document | Use it for |
|---|---|---|
| 1 | [mvp-scope-v1.1.md](mvp-scope-v1.1.md) | What is in the MVP, priorities (P0/P1/P2), blockers |
| 2 | [mvp-decision-record.md](mvp-decision-record.md) | The 12 approved decisions and binding copy/semantic rules C1–C8 |
| 3 | [mvp-user-journeys.md](mvp-user-journeys.md) | J01–J20, what each user does, errors, acceptance (read the v1.1 addendum too) |
| 4 | [feature-and-screen-inventory.md](feature-and-screen-inventory.md) | Every existing screen and its data; planned surface IDs A-xx, R-xx (addendum) |
| 5 | [screen-state-and-design-requirements.md](screen-state-and-design-requirements.md) | States each surface must handle (read the addendum too) |
| 6 | [api-mobile-contract-matrix.md](api-mobile-contract-matrix.md) | What data exists, field names, planned contracts, error texts |
| 7 | [mvp-readiness-gates.md](mvp-readiness-gates.md) | Measurable Design-Ready and Beta-Ready gates |
| 8 | [mvp-engineering-gap-matrix.md](mvp-engineering-gap-matrix.md) / [mvp-engineering-qa-roadmap.md](mvp-engineering-qa-roadmap.md) | What engineering will build and in what order |
| 9 | [mvp-qa-readiness.md](mvp-qa-readiness.md), [mvp-ops-dependencies.md](mvp-ops-dependencies.md), [mvp-ops03-and-staging-prerequisites.md](mvp-ops03-and-staging-prerequisites.md), [mvp-repository-audit.md](mvp-repository-audit.md) | Background evidence (not needed for wireframes) |

Superseded and kept as history: `mvp-scope-v1.md`, `mvp-design-readiness.md`.

## 2. Surface register

Readiness columns: **WF** = wireframes may start; **HF** = high-fidelity may start. "HF after DR-1/DR-9" means the
documentation merge and the owner-reviewed wireframes (gates in `mvp-readiness-gates.md`). **Eng. dependency** = what
engineering must deliver before the surface can be implemented (not before it can be designed).

### Foundation (exists today; may be restructured by design)

| Surface | Priority | Journeys | WF | HF | Eng. dependency / note |
|---|---|---|---|---|---|
| Sign-in | P0 | J01 | Ready | After DR-1/DR-9 | M11 (session expiry) |
| Dashboard | P0 | J12 | Ready | After DR-1/DR-9 | Inbox entry with attention indicator, no count (F-4); **no aggregate balance** |
| Accounts list/detail/create/edit | P0 | J02, J04 | Ready | After DR-1/DR-9 | F-2 adds floor/holds display (P1) |
| Income list/create/edit | P0 | J03 | Ready | After DR-1/DR-9 | BE-3 pagination |
| Expenses list/detail | P0 | J04 | Ready | After DR-1/DR-9 | BE-3 pagination |
| Categories (3 screens) | P0 | J04 | Ready | After DR-1/DR-9 | — |
| Budgets (3 screens) | P0 | J05 | Ready | After DR-1/DR-9 | — |
| Transfers list/create | P0 | J10 | Ready | After DR-1/DR-9 | Server-date label (MF-5) |
| Goals list/detail/create/edit | P0 | J06–J08 | Ready | After DR-1/DR-9 | F-2 floor warning |
| Goal priorities | P0 | J09 | Ready | After DR-1/DR-9 | — |
| Receipt upload and review | P0 | J11 | Ready | After DR-1/DR-9 | Receipts list is **deferred** (Q6) |
| Analytics, Financial Overview | P0 | J12 | Ready | After DR-1/DR-9 | Server-date label |
| Global states (loading, error with Retry, refresh, session expired) | P0 | all | Ready | After DR-1/DR-9 | MF-2, MF-3 |

### New surfaces

| ID | Surface | Priority | Journeys | WF | HF | Eng. dependency |
|---|---|---|---|---|---|---|
| A-01..A-03 | Sign-up, forgot password, reset password | P0 | J19, J20 | Ready | After DR-1/DR-9 | MF-4; staging Supabase settings (QA-1) |
| R-01 | Rules list | P0 | J13 | Ready | After DR-1/DR-8/DR-9 | F-1, F-3 |
| R-02..R-05 | Rule editors (income allocation, floor, overcommitment, budget alert) | P0 | J13, J14 | Ready | same | F-3; BE-1 |
| R-06 | Rule detail / lifecycle | P0 | J13, J14 | Ready | same | F-3 |
| R-07 | Rule preview | P0 | J14 | Ready (design the states in the addendum) | same | **BE-2**, F-5 |
| R-08 | Inbox | P0 | J15, J16 | Ready | same | F-4 |
| R-09 | Proposal detail | P0 | J15 | Ready | same | F-4 |
| R-10 | Alerts | P0 | J16 | Ready | same | F-4; alerts need E9A in the target environment |
| R-11 | Execution history | P1 | J18 | Ready | same | F-6 |
| R-12 | Floor warning pattern and Account capacity detail | P0 / P1 | J07, J17 | Ready | same | F-2 |

## 3. What designers may and may not decide

May decide: navigation structure (constraints: Inbox reachable from the Dashboard; rules in a stable area;
sign-up/recovery reachable from sign-in), grouping, wording within the copy rules, layout of every state, the shape of
the preview and Inbox presentations.

May not decide or assume: any new data field, aggregate figure, endpoint or backend guarantee; anything marked
deferred; a different meaning for reservation, release, transfer, reservable amount or Net.

## 4. Glossary and copy rules (frozen)

| Term | Meaning | Never say |
|---|---|---|
| Account | A place where money exists; balance may be negative | net worth, total balance |
| Reserve / Reservation | Earmark money inside an Account for a Goal; **no money moves; the Account balance does not change** | transfer, deposit, pay, move money |
| Release | Reduce a reservation; **no Transfer** | transfer back |
| Available to reserve (`reservable_amount`) | What the Account can still earmark | available cash, safe to spend |
| Transfer | Money moved between two owned Accounts, same currency; planned changes nothing until posted | — |
| Net (Financial Overview) | Recorded Income minus recorded Expenses | cash flow, balance |
| Proposal | A CONFIRM rule's suggested reservations awaiting the user; holds capacity until it expires (168 h) or is decided | — |
| Attention indicator | Non-numeric Dashboard marker: `attention` / `clear` / `unknown` (C7) | unread count, N new |
| Attention indicator | Non-numeric Dashboard marker: `attention` / `clear` / `unknown` (C7) | unread count, N new |
| Alert | A rule-detected condition: floor breached, overcommitted, budget watch/at risk/exceeded | — |

Binding rules (from the decision record): **C1** rules are checked when the app opens or refreshes and after income is
recorded, never promised "while the app is closed"; **C2** reservation is not a transfer; **C3** no invented
balances; **C4** state the server date where "today" matters; **C5** proposal outcome comes from `status`, not the HTTP
result; **C6** sign-up and recovery messages never reveal whether an email exists; **C7** the Inbox entry is a non-numeric attention indicator, `unknown` is never shown as `clear`; **C8** a preview is an example from a sample income, never a promise.

## 5. Data and behavior facts designers must know

- Errors will carry stable codes (BE-1); until then text only. Design error states per code family, with a neutral
  fallback for unknown codes.
- Lists other than rule lists are unpaginated today; Expenses and Income become paginated (BE-3). Design both.
- There is no 403: an object that is not yours looks like "not found".
- Confirm/reject of an already-decided proposal succeeds with the stored outcome: design all terminal outcomes
  (executed, partially executed, expired, rejected, cancelled).
- Alerts and the Inbox degrade when the alerts table is absent in an environment ("not available yet").
- Preview and rule outcomes use current balances and can change when income arrives.

## 6. Handoff checklist (per surface family; owner/designer use)

- [ ] Wireframe covers every state listed for the surface in the state document (or marks it `n/a` with a reason).
- [ ] Copy uses the glossary; no forbidden phrases.
- [ ] No invented data; every figure names its source field.
- [ ] Accessibility notes: name, role, non-color status, reorder without drag, announcement of async results.
- [ ] Dependencies on planned contracts (BE-1/2/3) are noted on the wireframe.
- [ ] Owner has reviewed (gate DR-9).
