# MVP-ACCEPTANCE-002 — Local simulator acceptance of J05–J10, J13–J18 and J20

Date: 2026-11-19. Repository commit: `main` @ `e7254e27b2e232d4e47e7fd97ebbc375b6851010` (PR #135 merged). Branch `qa/VF-MVP-ACCEPTANCE-002`.

**Evidence class: LOCAL SIMULATOR SMOKE.** This is **not** official acceptance. It is not staging, not a physical device,
not Android, and it does not produce any `PASS` row of
[qa-device-acceptance-template.md](qa-device-acceptance-template.md) (BR-5). It closes the "no UI evidence at all" gap that
[local-preflight-mobile-acceptance-001.md](local-preflight-mobile-acceptance-001.md) left for the journeys below. No hosted
Supabase, Render, production, staging or shared database was contacted. No credential, key or token is recorded here.

## 1. Environment

| Item | Value |
|---|---|
| Device | iPhone 17 Simulator, iOS 26.3, Expo Go 57.0.9 (not a development build; not the iOS 16.4 floor) |
| Auth | The real Supabase Auth (GoTrue) from [tools/local-auth](../../tools/local-auth/README.md), email confirmation on, Mailpit for mail |
| API | FastAPI, `AUTH_MODE=supabase`, loopback only |
| Database | Disposable database in a scratch PostgreSQL 18 cluster, **recreated empty and migrated to head `a3f9d7c25e84`** (so the `rule_alerts` table (E9A) exists, unlike a production that has not applied it) |
| Users | Synthetic users A (all journeys), B (isolation checks), R (password recovery) on a disposable Auth stack |
| Method | Journey actions were performed **in the UI**. Preconditions and verification used the API and direct SQL against the disposable database (marked "API" below). Screenshots are in [qa-evidence/acceptance-002](qa-evidence/acceptance-002/) |

## 2. Results

Every row is a result observed in this run. "Not exercised" lists what the journey definition asks for that this run did **not** do.

| Journey | Result | What was observed | Not exercised |
|---|---|---|---|
| J05 Budget | **PASS** | Created in UI (General, monthly, 300.00). List showed the backend's own values (spent 240.00, remaining 60.00, 80.00%, "At risk", projection). A malformed amount was refused client-side and nothing was written. Edit to 400.00 created budget version 2 and history was kept. Delete confirmed and the Expense/Account were untouched. Deleting a Budget used by a rule showed "Budget is referenced by a financial rule and cannot be deleted." | Category budgets, weekly/yearly periods, end-date 409 |
| J06 Goal | **PASS** | Created in UI; rank assigned by the backend (new Goals ranked after earlier ones); Goals list showed 0.00 saved | Currency immutability once history exists |
| J07 Reserve | **PASS** | Picker showed "Available to reserve" per Account. Reserving 300.00 against 200.00 available gave "Reservation exceeds the Account's reservable capacity." and wrote nothing (409). Reserving 300.00 from Main Checking: balance 760.00 unchanged, reserved 0→300.00, reservable 760→460.00, no Transfer, no new AccountTransaction; the form refreshed without reload and history showed "Reservation +300.00 EUR". API: replay of the same `client_request_id` gave 201 then 200 with one row; a changed payload under the same key gave 409 | Dropped-response drill on a device (BR-6) |
| J08 Release | **PASS** | "Withdraw from" was not preselected; partition listed 300.00. Releasing 100.00: reserved 300→200.00, reservable →560.00, balance unchanged, no Transfer, no ledger row. API: releasing 500.00 gave 409 `goal_partition_insufficient_funds` | Archived-Account partition |
| J09 Priorities | **PASS** | Reordered in UI and saved; the API and the Goals list show the saved order. A Goal added elsewhere made Save return 409; the app reloaded the latest order with "Goals changed while you were editing. The latest order has been loaded." and nothing was partially saved | A second physical device |
| J10 Transfer | **PASS** | Created in UI with a confirmation dialog ("…update both balances"). Posted: Main 760→610.00, Savings 200→350.00, total across the two Accounts unchanged at 960.00, Income and Expenses unchanged, two ledger rows added. API: replay gave 201/200 with one row; a future-dated transfer stayed `planned` with no ledger effect and was deletable | Currency mismatch, archived Account, posting a planned transfer in the UI |
| J13 Rule | **PASS** | Created three of the four rule types in UI ("Reserve from income", "Minimum unallocated amount", "Budget alert"); the fourth (overcommitment) was created by API. CONFIRM ("Ask me first") was preselected and listed first. Saving with no Goal showed "Choose at least one Goal." and wrote nothing. UI lifecycle draft → On → Paused (confirmation explains open suggestions are cancelled) → On; `effective_from` was the server date. Floor and budget-alert rules were turned on in UI | Edit-while-draft, Turn off, Delete rule, duplicate-rule 409 |
| J14 Preview / AUTO | **PASS** | An Automatic rule could not be turned on without an example ("Turn on (example first)"); the Example screen disabled "Turn on automatic rule" until an example for this version was shown. The example was labelled "Example only", showed the server date and rule version, used figures consistent with the Account (300.00 + 400.00 sample = 700.00; Holiday 50.00), and SQL confirmed it wrote nothing (0 executions, no new Goal rows). The consent dialog says rules are checked "when you open or refresh the app and after you record income. Nothing is checked at other times" and "No bank transfer takes place." The rule then executed on an Income at evaluation | "Editing a rule invalidates its preview" (automated tests only) |
| J15 Proposal | **PASS** | An Income plus an Inbox open produced a "Waiting for you" proposal ("Nothing is reserved until you confirm"). Confirm: dialog, then "Reserved"; Main Checking balance 1660.00 unchanged, reserved +100.00, no Transfer/AccountTransaction. A second proposal was declined in UI: nothing reserved, execution `rejected`. API: confirm/reject on a terminal proposal return 200 with the stored `executed` status and no second effect | Expiry (backend test layer only), stale-cancel 409 |
| J16 Alert | **PASS** | With an overcommitted Account, a Budget over its limit and a floor breach, evaluation created three alerts shown in the Inbox and the Alerts list; "Mark as reviewed" acknowledged one in UI. API: re-acknowledging returned 200 and kept the first timestamp; user B got 404. With the `rule_alerts` table temporarily renamed (disposable DB only, restored afterwards) the API returned `available:false`, the Alerts screen said "Alerts are not available yet." and the Inbox header said "Status unknown" (never "Up to date"). The Dashboard Inbox entry showed "Needs attention" with no number and no "unread" | Budget `watch`/`at_risk` escalation, episode resolution |
| J17 Floor | **PASS** | With a floor of 1500.00, a manual reservation that left 1460.00 succeeded and showed "Reserved, below your minimum… 1460.00 EUR… floor of 1500.00 EUR… Available for rules: -40.00 EUR… The floor is a guide, not a limit, and the Account balance did not change." The API figures matched. The hard rejection is J07. A rule allocation lacking capacity was **skipped** (`insufficient_capacity`), not warned | |
| J18 History | **PASS** | History listed recorded runs with status filters and "Showing 4 of 4". The skipped run read "There was not enough available to reserve after the minimum unallocated amount and other pending suggestions."; details expanded; the list states income not yet checked does not appear | Unknown-reason fallback in the UI (unit-tested only) |
| J20 Recovery | **PASS** | The request screen showed the same neutral message ("If an account can use <address>, we sent a link…") for an address that does not exist and for a real one; only the real address received mail. The mail link redirected to the app-unique scheme `valorfinis://auth/callback`. Delivered to the app, it opened "Choose a new password"; the API log showed **no data request** until the new password was saved. Afterwards the new password signed in (200) and the old one was refused (400). Re-delivering the **used** link showed "Link not valid… already used… Request a new link" and the user stayed signed out | Expired link by time, link opened without the app, password-policy failure, rate limit |

Additional checks made in the same run:

| Check | Result |
|---|---|
| M10 triggers | Observed `POST /financial-rules/evaluate` on **Inbox open**, **pull-to-refresh**, **app foreground** (13 evaluate calls over the run) and immediately after an **Income save** in the real form |
| Cross-user isolation | User B received 404 for user A's rule (get/patch/enable/preview), proposal (get/confirm), alert acknowledge and Goal transaction; B's own lists were empty. (GET on a single Goal/Account/Budget has no route, so those returned 405, not data) |
| API health | 372 requests (324×200, 28×201, 2×204), **0 five-hundreds, 0 tracebacks**. Every 4xx was deliberate: 5×409 (over-capacity reservation, over-release, key conflict, stale Goal set, Budget used by a rule), 9×404 (cross-user probes and an unknown alert id), 3×405 (routes without GET, my own probe) and 1×422 (my own malformed API body) |
| Metro | Only the known `SafeAreaView` deprecation warning |

## 3. Financial invariants (independent SQL reconciliation at the end of the run)

| Invariant | Observed |
|---|---|
| Account balance equals the sum of its ledger | Main Checking 1960.00 = 1000.00 opening − 240.00 expense + 1300.00 linked income − 100.00 net transfers; Savings Pot 10.00 = 200.00 + 400.00 − 690.00 + 150.00 − 50.00. API and SQL agree |
| Reservations equal the Goal ledger | Main Checking 400.00 and Savings Pot 50.00 equal the net linked contributions and withdrawals |
| A reservation or release moves no money | No balance, Transfer or AccountTransaction change (J07, J08, J15) |
| A Transfer is neither Income nor Expense | Income and Expenses were unchanged by every Transfer (J10) |
| Overcommitment is a status, not an error | Savings Pot (balance 10.00, reserved 50.00) reported reservable −40.00 without any error |
| A failed request writes nothing | Over-capacity reservation, malformed budget amount, stale priorities and preview: no row change |

## 4. Defects and observations

**Open Sev-1: 0. Open Sev-2: 0.** Severities per [qa-evidence-and-staging-isolation.md §7](qa-evidence-and-staging-isolation.md).

| ID | Sev | Finding | Evidence | Status |
|---|---|---|---|---|
| D-01 | 3 | On several forms the first tap on a button while the keyboard is open only dismisses the keyboard, so Save/Reserve/Withdraw/Send needs a second tap (seen on goal reserve and withdraw, transfer, floor reservation, reset request). Some forms (rule editors, budget/goal save) submitted on the first tap, so it is inconsistent. 21 of 49 `ScrollView`s set `keyboardShouldPersistTaps`. May be partly a Simulator hardware-keyboard effect | DB unchanged after the first tap in each case | open; confirm on a device |
| D-02 | 4 | Budget edit: a malformed amount shows "Limit amount must be greater than zero." (the value is not a number) | screenshot `j05-08` | open |
| D-03 | 4 | An executed proposal says "Expiry was <date>" although that date is still in the future | screenshot `j15-04` | open |
| D-04 | 4 | An overcommitment alert is headed "Below the minimum" although the Account has no minimum | screenshot `j16-07` | open |
| D-05 | 4 | On Reset password the status text keeps naming the previous address while the field shows a new one during the resend cooldown | observed | open |
| D-06 | 4 | A link to a non-existent route shows Expo Router's default dark "Unmatched Route" screen, unstyled, in English | observed with a malformed link | open |

Observations (not defects): the Budget projection after one day of a partial period extrapolates to a large figure (2880.00 on 240.00 spent in one day); it is the backend's value and is labelled a projection. The test harness itself was flaky (taps lost while a dialog closed or a screen hydrated; a stale Metro transform cache baked in an old app root and needed `--clear`); none of that is attributed to the app.

## 5. What this does not establish

Android; a physical device; the iOS 16.4 floor; a development build (native permission strings, `valorfinis://` link handling, PKCE in a real build); staging; hosted Supabase settings, SMTP and rate limits; idempotency "dropped response" drills on a device (BR-6, only API replay was checked); session expiry and request-timeout drills (BR-7); accessibility (BR-8); performance (BR-9); production migration state (E9A and later revisions are unapplied in production per the docs).

## 6. Conclusion

All thirteen journeys listed in the brief (J05–J10, J13–J18, J20) completed in the UI with no Sev-1/Sev-2 defect and no financial invariant violation. Together with the earlier local results (J01–J04, J11, J12, and registration/confirmation of J19 in `local-preflight-mobile-acceptance-001.md` §8) every journey J01–J20 now has at least local simulator evidence. Official BR-5 acceptance still requires staging and physical devices.
