# MVP Scope v1.1 (VF-MVP-ENG-003)

Version: **1.1, APPROVED** by the product owner via the decisions in [mvp-decision-record.md](mvp-decision-record.md).
Date: 2026-10-27. Supersedes [mvp-scope-v1.md](mvp-scope-v1.md) (kept as the historical audit input).
Code baseline: `main` @ `08d985c030a38823fe43863c806d90bbc86e97b4`; documentation baseline commit `7754a94`.

What changed from v1: every open question (Q1–Q12) is decided; registration and password recovery are added
(M14 split into M14a/M14b); the rule preview becomes in-scope backend work; error codes, pagination and the device
matrix are committed; the receipts list is deferred; priorities (P0/P1/P2) are assigned. Product objectives, target
users, canonical semantics and the deferred list are unchanged from v1 (§1–§3 and §6 there remain authoritative);
binding derived rules are in the decision record (C1–C8).

Status vocabulary: IMPLEMENTED, PARTIAL, MISSING, BLOCKED, UNKNOWN, DEFERRED (as defined in the audit).
Priority: **P0** required for MVP functional completeness; **P1** required for high-quality Beta readiness;
**P2** may be deferred without breaking the approved MVP.

## 1. In-scope domains

| Domain | Backend | Mobile | v1.1 position |
|---|---|---|---|
| Authentication and session | IMPLEMENTED (Supabase JWT, verified per request) | PARTIAL (sign-in/out only) | In scope; adds registration, recovery, session expiry |
| Dashboard | IMPLEMENTED | IMPLEMENTED (limited) | In scope; adds Inbox entry with attention indicator (no count); **no balance aggregate** (Q10) |
| Accounts and balances | IMPLEMENTED | IMPLEMENTED | In scope; adds floor/holds/rule-capacity display (P1) |
| Income, Expenses, Categories, Budgets | IMPLEMENTED | IMPLEMENTED | In scope; Expenses/Income paginated (Q7) |
| Account transfers | IMPLEMENTED | IMPLEMENTED | In scope |
| Goals and reservations, priorities | IMPLEMENTED | IMPLEMENTED | In scope; adds manual floor warning (P0) |
| Receipts and OCR | IMPLEMENTED | PARTIAL | In scope: upload, process, confirm. List/manage deferred (Q6) |
| Analytics and Financial Overview | IMPLEMENTED | IMPLEMENTED | In scope |
| Smart Rules (four types) | IMPLEMENTED | MISSING | In scope (Q1, Q11) |
| AUTO / CONFIRM | IMPLEMENTED | MISSING | In scope; AUTO under copy rule C1 (Q2) |
| Rule preview | **MISSING** | MISSING | In scope; backend endpoint required (Q3) |
| Rule proposals | IMPLEMENTED | MISSING | In scope |
| Alerts and Inbox | IMPLEMENTED (no Inbox endpoint) | MISSING | In scope; client-composed Inbox (Q9) |

## 2. Requirement register

IDs M01–M17 continue from v1. New or changed entries are marked **(v1.1)**.

| ID | Requirement | Layer | Priority | Class today |
|---|---|---|---|---|
| M01 | Rules: list, create, edit, enable/pause/disable, delete for four types | Mobile | **P0** | MISSING |
| M02 | AUTO / CONFIRM mode selection and explanation, CONFIRM presented first, copy rule C1 | Mobile | **P0** | MISSING |
| M03 | Rule preview: backend dry-run endpoint + mobile preview, required before AUTO enable **(v1.1: approved as (a))** | Backend + mobile | **P0** | MISSING |
| M04 | Proposals: list, detail, confirm, reject, expiry, terminal states (C5) | Mobile | **P0** | MISSING |
| M05 | Alerts: list, acknowledge, `available:false` handling | Mobile | **P0** UI; live behavior needs E9A (P1 ops) | MISSING |
| M06 | Inbox composed client-side from proposals, alerts and executions; Dashboard entry shows an attention indicator, **not a count** (rules in §M06 definition below) **(v1.1: Q9 A)** | Mobile | **P0** | MISSING |
| M07 | Execution history with plain-language reason codes | Mobile | **P1** | MISSING |
| M08 | Manual-reservation safety-floor warning display | Mobile | **P0** | MISSING |
| M09 | Account floor, holds, rule-capacity display and typing | Mobile | **P1** | MISSING |
| M10 | User-triggered `POST /financial-rules/evaluate` on foreground and Inbox open | Mobile | **P0** | MISSING |
| M11 | Session expiry (401) handling, cache clear on sign-out, request timeout | Mobile | **P0** | MISSING |
| M12 | Retry action on load failure; pull-to-refresh | Mobile | **P0** (retry), **P1** (offline cues) | MISSING |
| M13 | Receipts list/manage | Mobile | **P2, DEFERRED** (Q6) | MISSING by decision |
| M14a | Public sign-up **(v1.1)** | Mobile (Supabase Auth) | **P0** | MISSING |
| M14b | Password recovery: request, deep-link return, set new password **(v1.1)** | Mobile (Supabase Auth) | **P0** | MISSING |
| M15 | Machine-readable `code` on every error body **(v1.1: Q4 A)** | Backend, then mobile mapping | **P0** | MISSING |
| M16 | Pagination: Expenses and Income **(Q7)**; rule lists consumed paginated | Backend + mobile | **P0** rule lists; **P1** Expenses/Income; **P2** Transfers and others | MISSING |
| M17 | Verified unattended execution (Gate I) | Operations | **P1** (required only for any unattended claim) | BLOCKED/UNKNOWN |
| M18 | Server-date label on date-dependent screens **(v1.1: Q8 A)** | Mobile | **P1** | MISSING |
| M19 | Mobile CI (typecheck, lint, Node tests) and a `test` script | Engineering | **P0** | MISSING |
| M20 | Accessibility baseline on all P0 screens | Mobile | **P1** | PARTIAL |
| M21 | Query-key and invalidation definitions for all new families; receipt key includes user id | Mobile | **P0** (new families), **P1** (receipt key) | MISSING |
| M22 | Staging environment, seed/reset, device matrix execution **(v1.1: Q12)** | QA | **P0** for Beta | MISSING |

**P2 / deferrable without breaking the MVP:** M13, Transfers pagination, execution-history polish beyond M07, any
count endpoint (Q9 trigger-based), offline cues beyond retry.

## 3. Deferred (unchanged from v1 plus decisions)

VF-021 bank connections and import; investments; web client; push notifications; scheduled calendar-based
allocation; recurring transactions; bank-reconciled cash flow; FX reservations and cross-currency transfers;
shared accounts; Receipt/OCR expansion and the receipts list (Q6); an aggregate balance (Q10); device-date
contract (Q8); backend Inbox endpoint (Q9, until measured); mobile automated E2E until functionally complete
(CLAUDE.md), see the roadmap for the interim plan.

## 4. Dependencies

```text
Decisions Q1-Q12 (done)
   |
   +-- OPS-03 (release security corrections)      independent track; gates production, not design/implementation
   |
   +-- Mobile foundation (M11, M12, M19, M21)     first; no design dependency
   |       |
   |       +-- Auth surfaces (M14a/b)             needs staging Supabase config
   |
   +-- Backend contracts: BE-1 error codes, BE-2 preview, BE-3 pagination
   |       |
   |       +-- Smart Rules mobile VF-020F (M01-M10)   needs foundation + BE-1 + BE-2 + approved high-fidelity specs
   |
   +-- QA staging and infra (M22)                 needed before any device acceptance
```

Hard rules: one task, one branch; dependent tasks start only after the predecessor is merged; no production
release correction is mixed with feature work.

## 5. Acceptance requirements

The v1 acceptance list (§8 there) stands, with these v1.1 additions:
1. Registration and recovery work end to end on staging on both platforms, without revealing account existence (C6).
2. The preview endpoint writes nothing (no rows, no outbox event) and matches the execution result on the same
   state (parity test); enabling AUTO in the UI requires a preview for the current rule version.
3. Every error body returned by the backend contains a stable `code`; a contract test enforces uniqueness and
   non-removal; mobile handles unknown codes with a neutral fallback.
4. No screen contains forbidden copy (C1–C3); a repository grep check is part of CI or review (see gates).
5. Measurable gates in [mvp-readiness-gates.md](mvp-readiness-gates.md) are met; the gate document, not this one,
   defines pass/fail.

## 6. Known blockers (updated)

| ID | Blocker | Effect | Owner of closure |
|---|---|---|---|
| B1 | HIGH S1: hand-typed `alembic upgrade` in E9A/E10 runbooks on `main`; fail-closed runner only in local `c4fbd73` | Blocks production E9A/E10 and Beta; **not** design or implementation | OPS-03 |
| B2 | MEDIUM S2: Gate H stage 1 overclaim on `main` | Blocks Cron activation | OPS-03 |
| B3 | Preview endpoint does not exist | Blocks M03, AUTO enable UX | BE-2 |
| B4 | Production state UNKNOWN (revision, SHA, connectivity, E9A/E10) | Blocks any production claim | OPS Gate A |
| B5 | No Cron Job; P50 unverified | Blocks unattended claims only (copy rule C1 applies) | OPS Gates H/I |
| B6 | Error text has no code | Blocks rule-screen error handling quality | BE-1 |
| B7 | **New:** Supabase project settings for registration/recovery UNKNOWN (email confirmation, SMTP, redirect URLs, password policy, rate limits) | Blocks M14a/b acceptance | QA-1 / owner |
| B8 | **New:** no staging environment defined | Blocks all device acceptance (M22) | QA-1 / owner |
| B9 | **New:** URL scheme in `apps/mobile/app.json` is the generic `mobile`; recovery deep links need an app-unique scheme | Blocks M14b safety | MF-4 |

## 7. Open product decisions

None. Q1–Q12 are decided (see the decision record). Engineering-level open items (contract details of the
preview endpoint, the pagination compatibility strategy, timeout values) are owned by the tasks that deliver them
and are listed in the roadmap with their requirement sheets.

## M06 definition: Inbox attention indicator (review correction VF-MVP-ENG-003-R1)

Q9 stays decided as client-composed with no backend unread count. Consequence, binding for design and F-4: the
Dashboard Inbox entry carries an **attention indicator**, never a numeric unread count: the app has no read-state, the backend has no unread-count endpoint (Q9 A) and the rule lists are paginated, so any number would be partial or invented.

| Indicator state | Condition | Presentation rule |
|---|---|---|
| `attention` | At least one **loaded** item is demonstrably actionable: a proposal that awaits a decision (non-terminal status and not past its expiry) or an alert not yet acknowledged | Non-numeric marker plus accessible text "Inbox: needs your attention" |
| `unknown` | No actionable item is loaded **and** a necessary source is failed, incomplete or loading | Neutral entry; never shown as `clear`; the Inbox screen names the source and offers Retry |
| `clear` | No actionable item is loaded **and** every necessary source is authoritatively complete | Entry without marker; text may say "Nothing needs your attention" |

**Precedence (first match wins, evaluated in this order):**

1. `attention` if any loaded item is demonstrably actionable. A failed, incomplete or loading source elsewhere does not
   weaken this: an actionable item that was loaded is an existence proof.
2. Otherwise `unknown` if a necessary source is failed, incomplete or loading.
3. Otherwise `clear`, only if all relevant sources are authoritatively complete and no actionable item exists.

Necessary sources: the proposals source, the alerts source and, when it was attempted in this session, the `evaluate`
call. Executions are not a source for the indicator. A source is **authoritatively complete** only when its response
was received without error, did not report further pages (nothing remains beyond what was loaded), and, for alerts,
reported `available:true`. Alerts with `available:false` therefore keep the indicator at `unknown` (shown with "Alerts are
not available yet"), never `clear`.

Bounded cost: the client never fetches unbounded historical pages to manufacture `clear`. It requests the actionable
subset where the API provides a status filter, otherwise the first page only, and follows at most a small fixed number of
further pages (constant set in F-4, initial value 2). If completeness is not established within that bound, or the
bound is reached with more pages remaining and nothing actionable loaded, the state stays `unknown`. Staying `unknown`
is always acceptable; claiming `clear` falsely is not.

Rules: no number on the Dashboard entry; no word "unread" anywhere (there is no read-state; acknowledging an alert or
deciding a proposal is the only way an item leaves `attention`); inside the Inbox, per-source lists may show
"N shown" and "more available" but never a total that was not returned by the backend; failed executions are listed in
the Inbox history but do not drive the indicator (they have no user action in P0). The indicator is a presentation of
already loaded server data: the client does not compute financial values. An exact count would need a backend
endpoint and is not part of this MVP; adding one is a new decision (Q9 "if changed").
