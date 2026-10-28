# MVP Decision Record: Q1–Q12 (VF-MVP-ENG-003)

Date: 2026-10-27. Questions are quoted verbatim from `docs/mvp/mvp-scope-v1.md` §10 (VF-MVP-ENG-001).

## Provenance and how to amend

The product owner approved Q1–Q12, including public registration and password recovery (Q5). The approval message
did not list a per-question option except Q5. Each decision below is therefore recorded as the option recommended
in the VF-MVP-ENG-002 decision package, and Q5 as stated by the owner; Q12 is recorded with concrete floors
verified from the installed packages (see Q12). **If any approved answer differs from what is written here, the owner
amends this record; the "If changed" column states what would have to change.** Nothing here was inferred from
any source other than the owner's message and the ENG-001/ENG-002 documents.

Status vocabulary: APPROVED (owner), with the approved option letter as defined in the ENG-002 package.

## Decisions

| ID | Question (verbatim) | Decision | Effect on scope | If changed |
|---|---|---|---|---|
| Q1 | Are Smart Rules screens (M01–M10) part of MVP v1, or is MVP v1 the existing finance foundation plus Beta of rules later? | **A. Smart Rules screens are part of MVP v1**, sequenced after the mobile foundations (M11, M12). | M01–M10 are P0/P1 per the scope v1.1 boundary. VF-020F is in the MVP. | Rules move to a later release; workstream 4 and the Inbox leave the MVP and the Beta gate. |
| Q2 | May AUTO be offered before the scheduler is verified, with "evaluated when you open the app" copy? | **A. Yes.** AUTO is offered with honest copy: rules are evaluated when the app opens, refreshes, or after the user records income. Never "automatically while you sleep" or equivalent. | Copy rule C1 (below) binds all rule screens. Stronger claims require Gate I. | AUTO hidden until Gate I; v1 is CONFIRM-only. |
| Q3 | Preview: (a) add a backend dry-run endpoint, (b) drop the AUTO preview rule and rely on CONFIRM as the safe path, (c) client-side simulation. | **(a) Add a backend dry-run endpoint.** Client-side simulation is not permitted (CLAUDE.md: no duplicated backend calculations). Enabling AUTO requires the preview in the UX. | New backend task BE-2; preview is P0 because AUTO is in v1. | (b): preview leaves the MVP; AUTO enable gets an explicit consent step instead. |
| Q4 | Add stable error codes to the backend error body? | **A. Yes.** Additive `code` on every error body, before the rule screens. | Backend task BE-1; mobile error mapping keyed by code with string fallback. | Mobile keeps exact-string tables; X9 stays unfixable. |
| Q5 | Sign-up and password reset in MVP, or provisioned accounts only? | **Public registration and password recovery are in the MVP** (owner-stated). | New mobile auth surfaces and journeys J19–J20; Supabase Auth settings become a staging and release prerequisite. | Provisioned accounts only; J19–J20 removed. |
| Q6 | Receipts list/manage screen in MVP? | **A. Deferred.** Receipt upload and confirm only. | M13 moves to P2 (deferred). `GET/PATCH/DELETE /receipts` stay backend-only by decision. | A list screen is added to scope. |
| Q7 | Pagination for Expenses/Income/Transfers lists before Beta? | **A. Yes for Expenses and Income** before Beta; Transfers may follow later. Rule lists already paginated must be consumed paginated. | Backend task BE-3; mobile list changes; Beta gate item. | No pagination work; performance risk accepted. |
| Q8 | Timezone: server date vs device date for "today"? | **A. Server date for the MVP;** screens that depend on "today" display the date used. | Copy/label requirement; no contract change. | Device-date contract change across every effective-date rule. |
| Q9 | Inbox: client-composed, or add a backend summary/unread-count endpoint? | **A. Client-composed** from proposals, alerts and executions. A count endpoint is added only if composition is measured to be a problem. | Inbox is a mobile composition task (F-4); no backend work now. **R1 clarification (decision unchanged):** the Dashboard entry shows an attention indicator, not a numeric unread count (no read-state exists); see scope v1.1, M06 definition. | Backend summary and unread-count endpoint added to BE workstream. |
| Q10 | Any aggregate "total across accounts" on the Dashboard? | **A. No aggregate.** Per-Account figures only; currencies are never summed. | Dashboard shows no total; no backend work. | A definition (per currency, labelled) and backend support are required first. |
| Q11 | Which rule types ship in v1? | **A. All four:** `INCOME_ALLOCATION` (AUTO or CONFIRM, CONFIRM presented first), `MINIMUM_UNALLOCATED_FLOOR`, `OVERCOMMITMENT_ALERT`, `BUDGET_ALERT`. Alert rules are enabled only where the E9A table exists in the target environment. | Four editors; alert behavior in production depends on E9A (OPS). | Subset ships; editors removed. |
| Q12 | Minimum supported OS versions and device matrix. | **A. Defined matrix:** floors **iOS 15.1** and **Android API 24 (minSdk)** taken from the installed React Native 0.86.3 (`react-native/scripts/cocoapods/helpers.rb`, `gradle/libs.versions.toml`); plus the latest stable OS on each platform at test time. Physical devices: at least one iOS and one Android. The Expo SDK 57 documented floor, if higher, replaces these floors (task QA-0 confirms and pins). | QA matrix and Beta gate BR-5. | Matrix revised; Android may be re-scoped only by explicit owner decision. |

## Derived rules (binding on design and implementation)

C7 and C8 were added by review correction VF-MVP-ENG-003-R1; they restate consequences of Q9 and Q3 and change no decision.

- **C1 AUTO copy:** allowed: "Rules are checked when you open or refresh the app and after you record income."
  Forbidden: any wording implying execution while the app is closed, until Gate I is passed and recorded.
- **C2 Reservation semantics:** a reservation is an earmark inside an Account; it is never described as a transfer,
  deposit, payment or movement of bank money. A release creates no Transfer.
- **C3 No invented balances:** no "total balance", "safe to spend" or "available cash". `reservable_amount` is "available to reserve".
- **C4 Server date:** screens depending on "today" state the server date they use.
- **C5 Proposal result:** the outcome shown after confirm/reject is read from the returned `status`, never from the HTTP code.
- **C6 Registration messaging:** sign-up and recovery messages must not reveal whether an email already exists
  (behavior also depends on Supabase project settings, verified on staging).

- **C7 Inbox indicator:** the Dashboard Inbox entry shows an attention indicator (`attention` / `clear` / `unknown`), never a
  numeric count and never the word "unread". `unknown` (a source failed or is not fully loaded) is never shown as `clear`.
- **C8 Preview is hypothetical:** a rule preview is labelled as an example computed from the current balances and a
  sample income; it never reads as a promise, a reservation or a record of what happened (see BE-2 labelling requirements).

## Acceptance parameters awaiting owner confirmation (review correction VF-MVP-ENG-003-R1)

These are numeric targets proposed by engineering for gate BR-9. They are not product decisions Q1–Q12 and change none
of them. Gate BR-9 cannot pass until the owner records acceptance (or edited values) here.

| Parameter | Proposed value | Owner status |
|---|---|---|
| Performance budgets and conditions | Exactly as in [mvp-readiness-gates.md](mvp-readiness-gates.md), BR-9 and §2.2 | **PENDING owner acceptance** |
| Reference device per platform | The lowest-specification physical device of the owner-approved Q12 matrix | **PENDING** (matrix model names not yet recorded) |
