# VF-020F5 — Rule preview (R-07) and safe AUTO activation: implementation design sheet (for owner approval)

Status: **APPROVED by the owner (D1-D5, exactly as proposed); implemented in VF-020F5.**
This approves the R-07 implementation design only. It is not acceptance of the broader MVP release or the physical-device
gates; J14 AUTO acceptance on staging and devices remains PENDING until actually tested.
Scope: mobile only. The backend preview (BE-2, `POST /api/v1/financial-rules/{rule_id}/preview`) is merged and is the
authoritative contract (`docs/mvp/vf-be2-preview-contract.md`); older statements that preview is missing are historical.
Baseline: `main` `e14026995794949c9d9afe90a776d5c6e194d01b` (F1-F4, BE-2 merged).
Visual reference: the F3 conventions (`SafeAreaView` + `ScrollView`, `card`, `formGroup`/`label`/`input`, segmented
toggle, `button`, `noticeText`/`helperText`/`errorText`, `Alert` for confirmations). No new package.
Reused as-is: `financialRulesService.previewRule`, `buildPreviewRequest` (amount shape), `financialRuleKeys.preview`
(user + rule id + version + sample), `previewOutcomeInfo`, `previewEffectText`, `previewNoticeTexts`,
`describeRuleError` (`financial_rule_preview_not_available` already mapped), `planRuleInvalidation`.

## D1 — Route and entry point

| Route | Screen |
|---|---|
| `app/(app)/rules/[id]/preview.tsx` | Rule preview (R-07), feature code in `rule-preview-screen.tsx` |

Entry: on the Rule detail (R-06), an **"Example"** button for `INCOME_ALLOCATION` rules in every status (draft, on,
paused, off). Other rule types show no button (the backend's 409 `financial_rule_preview_not_available` is still mapped
to a controlled message if reached). For an AUTO rule that is not on, the disabled "Turn on" text of F3 is replaced by
"Turn on" -> opens this preview screen first (the gate below decides whether the final button is enabled). Back returns to
the rule detail. Recommended: **approve.**

## D2 — Sample income inputs

- **Amount** (required): decimal text field, shape-validated by the existing `buildPreviewRequest` (positive, at most 2
  decimals, <= 12 digits) *before* any request; the exact string typed is sent. **Prefill is empty** (no invented
  figure); a hint shows the Account currency only after a result (the backend derives it; the user never supplies one).
- **Source** (optional): chips "Not specified" (default, field omitted), salary, freelance, refund, gift, other. When
  omitted, no source check is reported; when the result says `source_selected_by_rule: false` it is shown distinctly.
- Button **"Show example"** (disabled while in flight and while the amount is invalid, with the reason as text). No
  automatic request on mount, on typing or on focus: the user always asks. Inputs are kept after any failure.
Recommended: **approve** (no default amount, explicit request).

## D3 — Result and failure presentations

Header on every state: a persistent label **"Example only"** and the line "If you received <amount> <currency>"
(amount verbatim from the response). Shown, all verbatim from the response: rule name/mode (from the rule read, not
re-derived), server `as_of_date` ("Server date") and `computed_at`, outcome with a text label (never colour alone),
per-Goal rows in server order (Goal name from the cached Goals when known, else "Goal"; `planned_amount` and
`selected_amount`), `planned_total`, `selected_total`, and the Account figures: actual reservable, assumed income credit,
hypothetical reservable, minimum unallocated floor, active rule holds, available rule capacity. No client addition,
subtraction, rounding or redistribution.

| State | Presentation |
|---|---|
| full | "Everything planned would fit" with the per-Goal rows. |
| partial | "Only part would fit" with the per-Goal `selected_amount` next to `planned_amount`. |
| skipped | "Nothing would happen" + mapped `reason_code` (e.g. `nothing_to_allocate`, `income_source_not_selected`), no rows. |
| blocked | "This rule could not run" + mapped `reason_code` (archived Account/Goal, currency mismatch, insufficient capacity). |
| effect `would_apply` (AUTO) | the existing text: hypothetical internal Goal reservations; no bank transfer. |
| effect `would_hold` (CONFIRM) | the existing text: hypothetical proposal and 168-hour hold; nothing reserved until confirmed. |
| effect `none` | "No allocation would be selected." |
| `source_selected_by_rule: false` | its own notice: "This income source is not one the rule uses, so the rule would not run." |
| notices | the three standing limitations always visible (sample income not recorded; other enabled rules not simulated; real-event eligibility not fully simulated) plus "This rule is not turned on" when the server sends it. |
| loading | spinner, inputs disabled. |
| failure | code-mapped message (401 session, 404 rule gone, 409 not available / other, 422 validation, timeout, network, unreadable response) with a **manual** "Try again" (never automatic); inputs kept. |

Never used on this screen: "reserved", "done", "will", "completed", "transaction". Never in the Inbox or any list of
real outcomes (C8). Recommended: **approve.**

## D4 — Version gating, staleness, confirmation

The AUTO authorization is **transient client state**, never persisted, scoped to the key
`(userId, ruleId, ruleVersion, sampleAmount, sampleSource)` and stored only after the backend returned a valid preview
**and the result was actually rendered** (set from the screen after the result is on screen, not at fetch time).

It is revoked on: sign-out / session rotation (state lives in the per-session client), any edit of the rule (version
change or the rule read changing), a different sample, a rule status/mode change, invalidation of the previews family by
a Goal or Account change (F1 events), and after a successful enable.

The preview screen shows "Out of date: this rule or your balances changed. Show the example again." when the loaded rule
version differs from the previewed one or an invalidation arrived; the old result stays visible but dimmed and
labelled, and it cannot authorize. The Rule detail only offers "Turn on" for AUTO after returning from a **current**
preview; otherwise it points to "Example".

Enable flow (single runner, below): refetch the rule (GET) -> require same id, same version, still AUTO and still
enable-able -> else "The rule changed. Show the example again." -> one POST `enable` (never resent). No claim of atomic
concurrency protection: the backend has no expected-version token, and the copy does not claim one.
Recommended: **approve.**

## D5 — AUTO activation copy and navigation

A confirmation dialog (title "Turn on automatic reservations?", buttons "Turn on" / "Cancel", no default-confirm) states:
1. This rule can set money aside for your Goals without asking you to confirm each eligible income.
2. No bank transfer takes place; a reservation is an earmark inside an Account.
3. Rules are checked when you open or refresh the app and after you record income. A rule is not guaranteed to run
   while the app is closed (C1).
4. The example was hypothetical; the actual outcome may differ.

After success: the authoritative status from the response is shown ("Automatic rule is on", from `status`/`execution_mode`
of the returned rule), caches invalidated by `rule_status_changed` (rules, this rule's previews, proposals, executions,
accounts), and the user returns to the Rule detail. After a failed enable: the mapped code message and the rule stays as
it was. After an **ambiguous** response (timeout, network, unreadable): no resend; one GET of the rule; if it now reads
as on, success is shown; otherwise "We could not confirm whether the rule was turned on. Check the rule before trying
again." CONFIRM rules keep the F3 flow: no preview needed, no gate.
Recommended: **approve.**

## Decisions requested

| # | Question | Recommendation |
|---|---|---|
| D1 | `rules/[id]/preview` route; "Example" button on the detail for allocation rules; "Turn on" for AUTO opens the preview first | Approve |
| D2 | Manual "Show example", empty amount prefill, optional source chips | Approve |
| D3 | Result/failure presentations and copy above, "Example only" on every state | Approve |
| D4 | Authorization scoped to user+rule+version+sample, set only after render, revoked on the events above, GET-recheck before enable | Approve |
| D5 | Confirmation dialog text, post-enable behaviour, ambiguous-outcome handling | Approve |

Out of scope: F6 execution history, backend/preview changes, migrations, any client-side financial calculation,
background scheduling, device/staging acceptance (J14 AUTO stays PENDING until actually tested).
