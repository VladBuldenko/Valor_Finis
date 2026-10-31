# VF-020F3 — Smart Rules list and editor: implementation design sheet (for owner approval)

Status: **PROPOSED, awaiting owner approval. No UI code has been written.**
Why this exists: the roadmap requires approved high-fidelity specs (gate DR-HF/DR-I) before the F-slices, and
`mvp-design-readiness.md` still lists "Rules ... screens (M01-M07, M10): NO - need approved scope, high-fidelity specs".
No approved specs for R-01..R-06 were found in the repository. This sheet uses the existing Goals / Accounts screens as
the visual reference (same `SafeAreaView` + `ScrollView`, `card`, `formGroup`/`label`/`input`, `selectControl` modal
picker, `typeToggleRow` segmented control, `button`/`editButton`/`deleteButton`, `noticeText`/`helperText`/`errorText`,
`Alert` for results). Nothing below adds a package.

## 1. Navigation (Expo Router, under `app/(app)/`)

| Route | Screen | Surface |
|---|---|---|
| `rules/index.tsx` | Rules list | R-01 |
| `rules/new.tsx` | Choose a rule type, then the matching editor | R-02..R-05 (create) |
| `rules/[id]/index.tsx` | Rule detail + lifecycle | R-06 |
| `rules/[id]/edit.tsx` | Edit (same editor, prefilled) | R-02..R-05 (edit) |

Entry: one new row "Rules" on the Dashboard link list, next to "Goals" (a plain link: no count, no badge - rule C7).
Feature code in `src/features/financial-rules/` (routes stay thin).

## 2. Screens and states

**R-01 List.** Rules in the backend order (`execution_order`/response order; not re-sorted). Card: name, type label,
status chip (Draft/On/Paused/Off), and for allocation rules the mode ("Ask me first"/"Automatic"). States: loading
(spinner), empty ("No rules yet" + Create rule), loaded, error with **Retry** (safe message, no body), pull-to-refresh.
A primary "New rule" button.

**R-02..R-05 Editors** (one form component per type, shared shell: name, optional description, Save, Cancel):

1. *Income allocation (R-02).* Order of fields: Account (picker, active Accounts only) -> **Mode: "Ask me first"
   (CONFIRM) listed first and preselected, then "Automatic" (AUTO)** with the C1 sentence -> Policy (fixed amount per Goal
   / percent of income) -> Percent (percent policy only) -> Goals to fund (1-50, active Goals in the Account's currency;
   per-Goal amount for fixed, optional cap for percent) -> Income sources (chips; default salary, freelance, gift, other;
   refund off) -> "Stop at each Goal's target" (default on) -> "Allow partial reservations" (default off) -> "Start from"
   date (optional; blank = the server date of the first turn-on). Copy: "A reservation sets money aside inside an Account for
   a Goal. It does not move any money in your bank."
2. *Minimum unallocated floor (R-03).* Account, floor amount (decimal string, >= 0). Copy: a threshold, not money removed.
3. *Overcommitment alert (R-04).* Account only.
4. *Budget alert (R-05).* Budget picker only.

Create saves a **draft** (`POST`), then goes to the detail screen. Edit sends only changed fields (`PATCH`). Inputs are
kept after a failed save; the Save button is disabled while a request is in flight (also guarded in the handler);
nothing is retried automatically. Validation is shape-only (required, decimal format, 1-50 targets, no duplicate Goal,
percent 0-100 with at most 2 decimals) and is explained before submit; the backend stays authoritative and its stable
error code is mapped (F1 `describeRuleError`). No client-side planning or outcome simulation.

**Material-edit notice (before Save).** Editing an *enabled* or *paused* allocation rule in any field except name and
description shows: "Changing this rule replaces any suggestions that are still waiting for you." (backend bumps `version`
and cancels open proposals).

**R-06 Detail / lifecycle.** Shows the stored configuration exactly as returned (amounts as strings), status, version-free
(version is not user-facing). Actions come from `ruleStatusInfo(status)`: Turn on / Pause / Turn off / Edit / Delete
(delete only for Draft or Off; the server may still refuse -> controlled message "Turn it off instead"). Each action
asks for confirmation where it changes behaviour (Pause, Turn off, Delete), disables itself while running, and on
success refetches the rules (F1 invalidation sets). Errors: 409 invalid transition, 409 archived subject, 422 currency
mismatch, 409 "cannot be turned on yet" (alert rules where the alerts schema is absent: the backend's
`financial_rule_activation_not_available` is shown as "Alerts are not available yet in this environment", not hidden),
404 rule gone. A link "History" is **not** included (F6).

## 3. AUTO gating (critical)

AUTO may be **selected and saved as a draft/edit** (it is just a configuration) but **cannot be turned on in F3**.
For an AUTO allocation rule the "Turn on" button is replaced by a disabled control with the text: "Turning on an
automatic rule needs an example first. That step arrives in an upcoming update. You can switch the rule to 'Ask me
first' to turn it on now." No other path enables AUTO (PATCH `execution_mode` on an *enabled* rule to AUTO is blocked
in the editor: for enabled/paused rules the mode control offers CONFIRM only, with the same explanation). F5 owns the
Preview UI and removes this gate.

## 4. Copy rules applied (C1-C8)

C1 "Rules are checked when you open or refresh the app and after you record income." on every AUTO mention, never
"while the app is closed"; C2 reservation is an earmark, never a transfer/deposit/payment; C3 only "Available to
reserve" and Account-scoped figures (no totals); C4 not applicable; C5 not applicable (F4); C7 no count or "unread";
C8 no preview in F3. The F1 forbidden-copy scan covers all new strings (they live in `src/features/financial-rules/`).

## 5. Accessibility

Every control has `accessibilityRole` ("button", "radio" for mode/policy, "checkbox"/"switch" for flags, "header" for
section titles) and a label that includes the current value; selected/disabled/busy via `accessibilityState`; errors
are announced with `accessibilityLiveRegion="polite"`; status is text, never colour alone; touch targets >= 44 pt.

## 6. Evaluation trigger

F3 does **not** mount `watchForeground` or call `evaluate` (F4 owns the Inbox-open trigger and the single mount point).
No duplicate foreground listeners are introduced.

## 7. Decisions needed from the owner

| # | Question | Recommendation |
|---|---|---|
| D1 | Approve this navigation (a "Rules" dashboard link and `rules/*` routes) and the field order above? | Approve |
| D2 | AUTO gating: may AUTO be *saved* (not enabled) before F5, or should AUTO be hidden entirely until F5? | Allow saving as above (shows the real mode, no loss on edit) |
| D3 | Alert-rule editors R-04/R-05 are enabled only where the alerts table exists. Show the editors and the real activation failure (as asked), or hide them until the environment is ready? | Show, with the backend failure explained |
| D4 | Delete confirmation wording and whether Pause/Turn off need a confirm dialog. | Confirm dialog for Pause, Turn off, Delete |
| D5 | High-fidelity visual specs: proceed with the existing Goals/Accounts look (above) as the F3 visual standard? | Yes; a later design pass may restyle all screens at once |

Out of scope for F3 (deferred): Preview UI and AUTO enable (F5), Inbox, proposals, alerts list, acknowledge (F4),
execution history and reasons screen (F6), evaluation trigger mounting (F4).
