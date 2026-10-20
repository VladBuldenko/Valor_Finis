# Product Requirements

## Problem

Users do not understand where their money goes and cannot control spending.

---

## Target User

- young professionals
- freelancers
- people who want to control spending

---

## MVP Scope

The MVP Scope and Out of Scope lists below are the original MVP scope and are
kept as historical context. The current planned scope is described in
"Current Scope Update (2026-10-05)" at the end of this document.

- add expense
- view expenses
- categorize expenses
- set budget limits
- set financial goals

---

## Out of Scope

- banking integrations
- AI recommendations
- investments
- automation

---

## User Stories

- As a user, I want to add an expense
- As a user, I want to see my monthly spending
- As a user, I want to track categories
- As a user, I want to set a budget
- As a user, I want to reach a goal

---

## Acceptance Criteria

- expense is saved
- expense is displayed
- filters work
- limits are calculated
- goals show progress

---

## Current Scope Update (2026-10-05)

The product has grown beyond the original MVP scope (accounts, income,
transfers, analytics and the Financial Overview are implemented). Two future
milestones change the original "Out of Scope" items. Neither is implemented yet.

### VF-020 Smart Goals & Rules (VF-020B–D implemented; VF-020E contract finalized, not implemented)

- The VF-020A contract is approved for documentation and implementation
  planning: `docs/modules/smart-goals-rules.md`. Implementation is authorized
  separately, stage by stage.
- Goals will be able to reserve (earmark) money that stays in an Account,
  alongside the existing tracked-only Goal progress. A reservation never moves
  money.
- Goals hardening (VF-020B) and the Account-linked reservations (VF-020C, backend
  and mobile) are implemented, and so are Goal priorities with the user lock
  (VF-020D, D5 revision `7c1e5a9b3d28`; production schema revision is now `115998e2e795`). A reservation is a Goal
  transaction linked to one Account, limited by that Account's reservable
  capacity (balance as of today minus existing reservations, scheduled
  outflows and planned outgoing Transfers); it never blocks real expenses or
  transfers, and an Account can then show as overcommitted. A withdrawal always
  names the partition (tracked, or one Account) it reduces. Rollout order:
  schema (C1) → production migration → backend (C2) → mobile (C3) (done). Goals
  are ordered by an explicit user-set priority (VF-020D). The Account safety
  floor, rules and alerts arrive with VF-020E (a `MINIMUM_UNALLOCATED_FLOOR` rule;
  warning-only for manual reservations, strict for rule allocations); VF-020E is
  backend only, the mobile rules UX is VF-020F. The VF-020E contract (v0.6) is
  finalized in `docs/modules/smart-goals-rules.md`; nothing of it is implemented.
- "Automation" is now in planned scope only as internal allocation rules: each
  rule runs in `AUTO` or `CONFIRM` mode, and both modes create or propose
  internal Goal reservations only.
- Bank and payment movement remains excluded: rules never initiate payments,
  transfers, direct debits or any change to a bank account.

### VF-021 Financial Connections & Import (separate future milestone)

- "Banking integrations" are now planned as a separate milestone: consent-driven,
  read-only connections to supported banks or financial applications, import,
  reconciliation and statistics.
- VF-021 is gated by provider, security, privacy and legal readiness. Its
  discovery may run in parallel with VF-020; no integration is implemented or
  authorized yet.

AI recommendations and investments remain out of scope.