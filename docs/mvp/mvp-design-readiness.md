> **Superseded by [mvp-readiness-gates.md](mvp-readiness-gates.md) (VF-MVP-ENG-003).** The tiers and criteria below
> were written before the decisions were approved and are kept as history.

# MVP Design Readiness Gate (VF-MVP-ENG-001, Part 9)

Date: 2026-10-27. Basis: `main` @ `08d985c030a38823fe43863c806d90bbc86e97b4`.

Production readiness is **not** a prerequisite for offline UX work. This gate separates four readiness tiers so
that design can start as early as it safely can without any claim about production or Beta.

## 1. Entrance criteria for UI/UX design

| # | Criterion | Status | Evidence | Remaining |
|---|---|---|---|---|
| 1 | Approved MVP scope | **PROPOSED, not approved** | [mvp-scope-v1.md](mvp-scope-v1.md) | Product owner resolves Q1–Q12 (at minimum Q1, Q2, Q3, Q5, Q6, Q9, Q10, Q11) |
| 2 | Complete screen inventory | **MET** | [feature-and-screen-inventory.md](feature-and-screen-inventory.md): all 28 route screens (plus 2 layouts), 11 feature directories, 12 missing Smart Rules surfaces | Update when navigation changes |
| 3 | Agreed primary user journeys | **DRAFTED, not agreed** | [mvp-user-journeys.md](mvp-user-journeys.md) J01–J18 | Owner and design review; J13–J18 depend on Q3 and Q4 |
| 4 | Stable financial terminology and semantics | **MET (documented)** | Scope §3 table; reservation ≠ transfer; release ≠ transfer; reservable ≠ bank cash; Net ≠ cash flow | Owner confirms the glossary; copy deck still to be written |
| 5 | Actual API capabilities known | **MET** | [api-mobile-contract-matrix.md](api-mobile-contract-matrix.md) from OpenAPI (67 operations), 12 discrepancies | Re-run the OpenAPI inventory if the backend changes |
| 6 | Missing mobile features identified | **MET** | Scope §5 M01–M17; inventory §4 | — |
| 7 | Screen state matrix completed | **MET (draft)** | [screen-state-and-design-requirements.md](screen-state-and-design-requirements.md) | Design review; fill state copy |
| 8 | Critical implementation dependencies classified | **MET** | Scope §7/§9; ops document | — |
| 9 | QA requirements mapped | **MET (draft)** | [mvp-qa-readiness.md](mvp-qa-readiness.md) gap matrix G01–G18 | Owner picks device matrix (Q12) |
| 10 | Open product decisions documented | **MET** | Scope §10, Q1–Q12 | Answers |

Blocking unknowns that design must plan around, not wait for: no rule preview endpoint (Q3); no machine-readable
error codes (Q4); no Inbox endpoint (Q9); no pagination (Q7); unattended execution unverified (affects copy).

## 2. Readiness tiers

### A. Ready for UX research and wireframes — **YES**

Allowed now: user research on the foundation flows (J01–J12) and on how people think about earmarking money;
wireframes for every existing screen (restructured navigation is allowed and encouraged); **low-fidelity wireframes
of the Smart Rules surfaces** using the state matrix, with two variants where a decision is open (with and without a
preview step; with and without an aggregate Inbox badge).

Conditions: designers use the glossary in scope §3; no invented figures ("total balance", "safe to spend");
rules copy never says "automatically while the app is closed"; nothing in wireframes assumes a backend
capability marked MISSING without a visible dependency note.

### B. Ready for final high-fidelity UI specifications — **NOT YET**

Required first: criterion 1 (scope approved) and the specific answers to Q1 (are rules screens in v1), Q3 (preview
approach), Q5 (sign-up/reset), Q6 (receipts list), Q9 (Inbox composition), Q10 (dashboard aggregates), Q11 (rule types
in v1). Journeys J13–J18 agreed. For the **foundation screens only** (J01–J12), high-fidelity specifications may
start once criteria 1 (for those domains) and 3 are agreed; rules surfaces wait for Q3/Q4.

### C. Ready for implementation — **PARTIALLY**

| Work | Ready? | Reason |
|---|---|---|
| Mobile foundations: session-expiry (401) handling, request timeout, cache clear on sign-out, retry action, pull-to-refresh (M11, M12) | **YES** | Not design-dependent beyond minimal states; unblock everything else |
| Mobile CI (typecheck, lint, Node tests) (G01) | **YES** | Pure engineering |
| Manual floor-warning display (M08) and Account capacity typing (M09) | **YES, after copy approval** | Backend already returns the data |
| Backend: error codes (Q4), preview endpoint (Q3a), pagination (Q7) | **After owner decisions** | Contract changes need approval |
| Rules, proposals, alerts, Inbox screens (M01–M07, M10) | **NO** | Need approved scope, high-fidelity specs, and Q3/Q4 |
| Production migrations or Cron | **NOT part of this tier; separately gated** | S1, S2 blockers; Gates A–I |

### D. Ready for full Beta acceptance — **NO**

Not claimed. Required evidence (none exists today): S1 and S2 corrections merged and CI green; Gate A output and
E9A/E10 applied and verified; an observed scheduled run if any "automatic" claim is made; rules screens built and
accepted on physical iOS **and** Android against staging; session/timeouts and mobile CI in place; stored device
checklist results; accessibility pass; offline/dropped-response drills. See ops document §6.

## 3. Recommended order (summary; full plan in the final report)

1. Owner decisions Q1–Q12 (parallel with step 2).
2. Design: wireframes (tier A) while engineering does foundations (tier C, YES rows).
3. Backend contract additions the owner approves (error codes, preview, pagination).
4. High-fidelity specs (tier B) then Smart Rules mobile implementation.
5. Publish the OPS corrections and run the production gates on their own track.
6. Device QA on staging; Beta only after tier D evidence.
