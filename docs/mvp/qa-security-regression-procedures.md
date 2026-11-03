# Security and Regression Procedures: SP-01 to SP-18 (QA-0)

Date: 2026-11-03. Basis: `main` @ `8bb98fb4ae07602825a9f44b8ada5561947ef913`.
Companion to [qa-device-acceptance-template.md](qa-device-acceptance-template.md); evidence rules in
[qa-evidence-and-staging-isolation.md](qa-evidence-and-staging-isolation.md); gates in [mvp-readiness-gates.md](mvp-readiness-gates.md).

**Nothing in this file has been executed.** All 36 results are `NOT RUN`. No staging environment, build or physical device exists yet.

## 1. How to read a procedure

Every procedure separates two layers. Do not merge them in a report.

- **APP**: behavior observed on the device (what the screen shows, which controls exist, what the user can do). This is the default evidence.
- **OPS**: a backend or operational fact that the screen cannot prove (a database row count, a server log line, a Supabase setting, an HTTP replay). An OPS step is run only by an operator, only on the `ACTIVE` staging environment, only read-only, and only when the owner authorized it for the run. Each result is saved as an assertion record (isolation document, section 6).
  **A report never says "the row count was checked" unless the assertion record exists.** Otherwise it says "app-observed only", and a gate that needs database evidence (BR-6, BR-12) stays open.

Procedures run on **each** physical platform. A procedure that cannot be arranged on staging (for example no second device, or the alerts table is in only one state) is `BLOCKED` with the reason; it is never marked `PASS` by assumption. Test users are QA-A and QA-B; no real data.

## 2. Procedures

### SP-01 — Expired session and reauthentication

- **Gates:** BR-7, M11
- **Layer:** APP observes; OPS creates the expired state
- **Setup:** Signed in as QA-A on a list screen with data loaded. Staging only.

Steps:
1. [OPS] The staging operator revokes QA-A's sessions in the staging Supabase project (or the access token is allowed to expire with refresh unavailable). Never done on production.
2. On the device, pull to refresh, then open another screen.
3. Sign in again as QA-A. Then repeat steps 1–2 and sign in as QA-B instead.
4. Separately, let a session auto-refresh with a healthy network (same user, no revocation).

Expected (app level):
- Within one request the app ends the session and shows the sign-in screen with 'Your session has expired. Please sign in again.'
- No QA-A figure is visible after signing in as QA-B (cache cleared; see SP-03).
- A healthy auto-refresh signs nobody out and does not reload the whole app.
- A refresh that fails only because the network is down does not sign the user out (see SP-16).

Backend or operational verification: [OPS, only if authorized] HTTP replay of a revoked token returns 401 from the staging API. Record as an assertion record, otherwise report 'app-observed only'.

Evidence: Screen recording or screenshots of the sign-in screen and message; build and device recorded in the row.

### SP-02 — Network timeout, lost responses and Retry

- **Gates:** BR-7, BR-6
- **Layer:** APP
- **Setup:** Signed in as QA-A. A way to stall or drop traffic: airplane mode toggled at the moment of the tap, or an operator-run delaying proxy in front of staging. Timeouts are 30 s (60 s for receipt upload) per the MF-2 policy; confirm the constants in `apps/mobile/src/api/api-transport.ts` before the run.

Steps:
1. Open a list screen while traffic is stalled. Time the wait with a stopwatch.
2. When the error appears, restore the network and tap Retry.
3. Submit a create (Income, Transfer or Goal reservation) and drop the connection immediately after tapping Save. Restore the network. Do not tap Save again yet.
4. Check the list, then repeat the same submission once.

Expected (app level):
- A stalled read ends at the timeout (near 30 s) with a plain message and a Retry control; no screen waits forever.
- Retry re-reads only; it sends no write.
- A write is never re-sent automatically. For rules, 'We could not confirm whether this went through. Check the list before trying again.' is shown where the answer never arrived.
- A deliberate second submission of the same form reuses the same attempt key, so exactly one record results (see SP-08).
- No raw backend text, URL, stack trace or token is shown.

Backend or operational verification: [OPS, only if authorized] Count of rows created for the test records (assertion record). Without it the report says 'app-observed only'.

Evidence: Stopwatch times in the row; screenshots of the error and Retry state; list state after restore.

### SP-03 — Sign-out and sign-in user isolation

- **Gates:** BR-10 (ownership), MF-2
- **Layer:** APP
- **Setup:** Seeded users QA-A and QA-B with visibly different data (Account names `QA-A-*` and `QA-B-*`).

Steps:
1. Sign in as QA-A and open Dashboard, Accounts, Goals, Inbox.
2. Sign out. Use the system Back gesture and the app switcher to look for stale screens.
3. Sign in as QA-B and open the same screens.
4. Kill and reopen the app while signed in as QA-B.

Expected (app level):
- After sign-out no QA-A data is reachable by Back or from the app switcher snapshot beyond the OS snapshot of the last screen.
- QA-B sees only QA-B data on every screen, including cached screens opened earlier as QA-A.
- A reopened app shows QA-B, never QA-A.

Backend or operational verification: [OPS, only if authorized] Cross-user read by id returns 404 from the API (assertion record). Otherwise 'app-observed only'.

Evidence: Paired screenshots (QA-A view, QA-B view) with the data names visible.

### SP-04 — A → B → A identity rotation

- **Gates:** BR-10, MF-2
- **Layer:** APP
- **Setup:** QA-A and QA-B as in SP-03. A screen with a slow read to hold a request in flight (stalled network from SP-02 for the first step).

Steps:
1. As QA-A, open a list and stall the network so a read is in flight.
2. Sign out, sign in as QA-B, restore the network.
3. Open the same list as QA-B. Sign out and sign in as QA-A again.
4. Open the same list again; pull to refresh.

Expected (app level):
- A late response for QA-A never appears under QA-B.
- After A → B → A, QA-A sees fresh QA-A data and no QA-B data at any point.
- A Retry button captured before the identity change sends nothing for the new user.
- No loop of repeated requests follows the sign-ins.

Backend or operational verification: [OPS, only if authorized] Staging request log shows no QA-B request authenticated as QA-A and the reverse (operator assertion). Otherwise 'app-observed only'.

Evidence: Screen recording across the three sign-ins.

### SP-05 — Foreground and background refresh

- **Gates:** MF-3, BR-7
- **Layer:** APP
- **Setup:** Signed in as QA-A on Dashboard; another session (second device or the API console) changes data while the app is in the background.

Steps:
1. Send the app to the background for at least 30 s, change a record from the other session, then return to the app.
2. Return again immediately without leaving (open and close the notification shade; this must not count as a return).
3. Background the app while a read is in flight, then return.
4. Background the app while signed out (sign-in screen) and return.

Expected (app level):
- Returning refreshes the visible screen's data once; the changed record appears without a manual refresh.
- A shade pull-down or a repeated 'active' event does not cause another refetch.
- No duplicate request for a read already in flight.
- Nothing is requested while signed out.
- Typed form input on a screen is not lost by the refresh.

Backend or operational verification: None required. Request counts are app-observed (a network proxy log is optional supporting evidence).

Evidence: Before/after screenshots and the time of the return.

### SP-06 — Incorrect or missing staging connectivity

- **Gates:** BR-5, QA-1
- **Layer:** APP; the isolation proof is OPS
- **Setup:** A build that is deliberately not configured for staging connectivity. Never point a build at production for this test.

Steps:
1. Install a build with an unreachable staging API origin (for example a reserved example.invalid origin supplied by the builder) and open the app.
2. With a correct build, switch the device to a network that blocks the staging origin and sign in.
3. Run `tools/qa/staging-fingerprint.mjs` for the correct build and for the deliberately wrong one.

Expected (app level):
- The app shows a plain 'Unable to reach the server' or 'Unable to reach the sign-in service' message and a way to retry; it does not crash or show an endpoint.
- The fingerprint helper exits non-zero with 'NOT VERIFIED' for the wrong build and 'VERIFIED' only for the staging build.
- A missing required environment value fails loudly at start, with the variable name only (never its value).

Backend or operational verification: [OPS] The register entry and the fingerprint output are the isolation evidence; there is no health-based proof (`/health` is identical in every environment).

Evidence: Screenshots of the messages; `artifacts/staging-fingerprint.txt` for both builds.

### SP-07 — Goal reservation versus Account balance semantics

- **Gates:** BR-5 (J07, J08), C2
- **Layer:** APP
- **Setup:** Account with a known balance (1000.00) and an active Goal in the same currency.

Steps:
1. Reserve 200.00 from the Account for the Goal.
2. Open Account detail, Account ledger, Goal detail and Transfers.
3. Release 50.00 of the reservation.
4. Search all visible text for 'transfer', 'deposit', 'payment' and 'moved'.

Expected (app level):
- After reserving: current balance still 1000.00; reserved 200.00; available to reserve reduced by 200.00; no new ledger row; no new Transfer.
- After releasing: reserved 150.00; available to reserve up by 50.00; current balance still 1000.00; Transfers unchanged.
- No screen describes a reservation as a transfer, deposit, payment or movement of bank money.

Backend or operational verification: [OPS, only if authorized] Row assertion: one goal_transactions row with the account id, no account_transactions row (assertion record).

Evidence: Account detail and Goal detail screenshots before and after each step.

### SP-08 — Transfer and Goal transaction idempotency

- **Gates:** BR-6
- **Layer:** APP observes; OPS counts rows
- **Setup:** Two same-currency Accounts and a Goal. Ability to drop the connection right after tapping Save.

Steps:
1. Create a Transfer and drop the connection immediately after tapping Save. Restore the network. Submit the same form again without changing it.
2. Repeat for a Goal reservation (`client_request_id` is required with an Account).
3. Repeat for a proposal confirm (SP-11) and an acknowledge (SP-12).
4. Change the amount and submit with the same form (a different payload).

Expected (app level):
- Exactly one Transfer and one reservation exist after the retry (list and balances reflect one).
- An identical replay is accepted as the same record (HTTP 200 replay) and shows no error.
- A different payload under the same attempt key is refused with the plain conflict message, never silently merged.

Backend or operational verification: [OPS, only if authorized] Row counts for the test records before and after (assertion record). BR-6 requires this DB evidence; app-observed results alone do not close BR-6.

Evidence: Lists before and after; the assertion record where authorized.

### SP-09 — Rule preview is hypothetical

- **Gates:** BR-5 (J14), C8
- **Layer:** APP observes; no-write proof is a backend test
- **Setup:** An income-allocation rule with Goal targets; the Account, Goals and Inbox noted before the test.

Steps:
1. Open the preview with a sample income and read every label.
2. Change the sample income and look at the preview again.
3. Edit the rule, then return to the preview.
4. Compare Account balances, reservations, Inbox and History with the notes taken before.

Expected (app level):
- The preview is labelled 'Example only' and states that nothing was recorded or reserved and that a real income may differ.
- A changed example or an edited rule marks the old preview out of date; AUTO cannot be enabled from a stale preview.
- No balance, reservation, proposal, alert or History row changes because of the preview.
- The preview is never listed as an outcome or history item.

Backend or operational verification: The backend no-write proof is the BE-2 test suite (state-snapshot, read-only transaction); do not claim a device-level database check unless an assertion record exists.

Evidence: Screenshots of the preview and of the before/after state.

### SP-10 — AUTO authorization invalidation

- **Gates:** BR-5 (J14), BR-12
- **Layer:** APP
- **Setup:** An AUTO rule that has been enabled after a preview of its current version.

Steps:
1. Edit a material field of the AUTO rule (amount, Goal target or source).
2. Open the rule and try to re-enable it without a new preview.
3. Preview the new version, then enable.
4. Pause the rule while it has no open proposal; then pause one that has an open proposal.

Expected (app level):
- A material edit invalidates the earlier preview authorization; AUTO is offered again only after a preview of the current version.
- Copy never promises execution while the app is closed (rule C1).
- Pausing or disabling cancels open proposals; the Inbox no longer offers them.

Backend or operational verification: [OPS, only if authorized] The rule version number and proposal status in the staging database (assertion record).

Evidence: Screenshots of the gate before and after the edit.

### SP-11 — CONFIRM proposal confirmation and rejection

- **Gates:** BR-5 (J15), BR-6, BR-12, C5
- **Layer:** APP observes; OPS counts effects
- **Setup:** A CONFIRM rule and two eligible Incomes so two proposals exist; a third for the expiry display.

Steps:
1. Open a proposal; confirm it.
2. Confirm the same proposal again (replay, or from the second device).
3. Reject the other proposal; reject it again.
4. Open a proposal that is expired, cancelled or stale if one can be arranged on staging.

Expected (app level):
- The result shown comes from the returned `status` (executed, executed_partial, rejected, expired, cancelled), never from HTTP 200.
- A replay shows the stored terminal state and creates no second effect.
- A stale proposal shows the 'no longer confirmable' state; nothing was written.
- Confirming only creates reservations; the Account's current balance does not change.

Backend or operational verification: [OPS, only if authorized] Reservation row count equals the applied items once (assertion record). Expiry after 168 h is covered by the backend test layer, not by waiting.

Evidence: Screenshots of each end state; the assertion record where authorized.

### SP-12 — Alerts unavailable versus empty

- **Gates:** BR-5 (J16), BR-12
- **Layer:** APP
- **Setup:** Two staging states: alerts table present with no alerts, and alerts table absent (`available:false`). If only one state exists, the other row is BLOCKED.

Steps:
1. Open the alerts list in the state with the table present and no alerts.
2. Open it where the alerts feature is unavailable.
3. Open the Dashboard Inbox entry in each state (see SP-13).

Expected (app level):
- Present and empty: a plain empty state. Unavailable: 'Alerts are not available yet.' Never the empty state.
- The unavailable state never lets the Inbox indicator read 'Up to date'.

Backend or operational verification: [OPS] Which state staging is in (alerts table present or not) is an operator fact; record it in the run record, not as a guess.

Evidence: One screenshot per state.

### SP-13 — Inbox attention, clear and unknown states

- **Gates:** BR-5 (J15, J16), C7
- **Layer:** APP
- **Setup:** Ability to create: an actionable item, a failing source (airplane mode or blocked request), and an all-empty state.

Steps:
1. With an open proposal or unacknowledged alert, read the Dashboard Inbox entry and the Inbox.
2. Clear everything actionable with all sources loaded.
3. Repeat with one source failing and nothing actionable; and with the alerts feature unavailable.
4. Turn on a screen reader and read the three entries.

Expected (app level):
- Actionable item present: 'Needs attention' (even if another source failed or is loading).
- Nothing actionable and every source complete: 'Up to date'.
- Any source failed, loading, unavailable or not fully paged and nothing actionable: 'Status unknown', never 'Up to date'.
- No count and no word 'unread' anywhere; the three states have different accessible names; Dashboard and Inbox agree.

Backend or operational verification: None required.

Evidence: Screenshots of the three states on Dashboard and Inbox; screen-reader transcript lines.

### SP-14 — Execution history without invented recovery

- **Gates:** BR-5 (J18)
- **Layer:** APP
- **Setup:** Executions in several statuses including blocked and skipped, and one with an unknown reason code if staging can produce it.

Steps:
1. Open History and expand a blocked and a skipped execution.
2. Look for any retry, recover or 'will be retried' wording.
3. Pull to refresh; filter by status.
4. Compare a card's amounts with the API console value.

Expected (app level):
- Each non-success shows a plain-language reason; an unknown code shows neutral text and is never echoed.
- No promise of retry or recovery is made; no recovery button exists.
- Amounts are the backend decimal strings; a null applied amount reads 'Not applied'.
- The screen sends no evaluate request and performs no write.

Backend or operational verification: None required.

Evidence: Screenshots of the expanded cards.

### SP-15 — The three authorized rule evaluation triggers

- **Gates:** BR-12, G18
- **Layer:** APP observes; OPS asserts exactly-once
- **Setup:** An enabled eligible CONFIRM rule and an eligible Income. The only authorized triggers in the app are: app foreground (background to active), opening the Inbox, and a successful Income create. Debounce 750 ms, cooldown 30 s for the first two.

Steps:
1. Record an Income, then immediately open the Inbox and foreground the app within the debounce window.
2. Wait over 30 s, background and foreground again.
3. Record a second Income while an evaluation is running.
4. Check Inbox and History.

Expected (app level):
- Rapid triggers collapse into at most one run plus one trailing run; no run overlaps another.
- Exactly one proposal exists per eligible Income, regardless of how many triggers fired.
- A failed evaluation is shown honestly (incomplete or failed status) and is never silently retried.
- No copy claims execution while the app is closed.

Backend or operational verification: [OPS, only if authorized] One execution row per eligible Income (assertion record). The server-side dispatcher is out of scope for the mobile run and is not claimed.

Evidence: Inbox and History screenshots with timestamps; the assertion record.

### SP-16 — Offline and reconnect handling

- **Gates:** BR-7, G12
- **Layer:** APP
- **Setup:** Signed in as QA-A with data loaded.

Steps:
1. Enable airplane mode with the app open; navigate between loaded screens and pull to refresh.
2. Try to save a form while offline.
3. Restore the network without touching the app; then foreground the app.
4. Launch the app from cold while offline.

Expected (app level):
- Loaded data stays visible with a clear refresh-failure notice; a failure with no data is shown as an error with Retry, never as empty.
- An offline save fails with a plain message and no duplicate; no queued silent resend.
- Reconnecting and foregrounding refreshes the data; the user is not signed out by the outage.
- A cold start offline shows the stored session's screens as errors with Retry or the sign-in service message, without a crash.

Backend or operational verification: None required.

Evidence: Screenshots offline and after reconnect.

### SP-17 — Accessibility and screen-reader checks

- **Gates:** BR-8, M20
- **Layer:** APP
- **Setup:** iOS: VoiceOver, larger text, reduce motion. Android: TalkBack, font size and display size at largest, high contrast text. Walk J01–J12 and J15–J16 (the BR-8 scope).

Steps:
1. With the screen reader on, move through each screen and every control.
2. Complete the money flows (J02–J04, J07, J10) using only the screen reader.
3. Check Inbox states, errors, Retry and refresh announcements.
4. Repeat at the largest text size and check nothing is clipped or unreachable.

Expected (app level):
- Every interactive element on a P0 screen has an accessible name and role; state (selected, expanded, busy) is announced.
- Errors and refresh failures are announced as alerts; meaning is never carried by colour alone.
- At the largest text scale controls stay reachable.
- Zero critical findings is the BR-8 bar; each finding is a defect with a severity.

Backend or operational verification: The scripted count of accessible names is a separate MF-5 deliverable; this procedure is the manual pass only.

Evidence: Notes per screen, screen-reader recordings or transcript excerpts, defect IDs.

### SP-18 — Cross-currency display without misleading aggregates

- **Gates:** BR-13, Q10, C3
- **Layer:** APP
- **Setup:** QA-A with Accounts in at least two currencies and Income and Expenses in both, including one record without a base-currency conversion if staging can produce it.

Steps:
1. Open Dashboard, Accounts, Overview and Analytics.
2. Look for any figure that adds amounts of different currencies.
3. Search for the phrases 'total balance', 'safe to spend', 'available cash' and 'net worth'.
4. Open a figure flagged as incomplete or unresolved.

Expected (app level):
- Balances appear per Account in the Account's own currency; no combined 'total across accounts' on the Dashboard.
- Unresolved conversion counts are surfaced, not hidden.
- No screen uses the forbidden phrases; 'available to reserve' is used for reservable amounts.

Backend or operational verification: None required.

Evidence: Screenshots of each screen with the currencies visible.

## 3. Procedure results

36 rows: SP-01 to SP-18 on iOS and Android. Copy this table to `qa-evidence/<run-id>/procedures.md` and fill the copy. The status rules are the same as for journey rows (acceptance template, section 2), except that a procedure can never be `WAIVED`.

| Result ID | Procedure | Platform | Status | Device model and OS | App build identifier | Staging environment identifier | Actual result | Evidence location | Defect reference | Blocker reference | Tester | Execution date |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SPR-IOS-01 | SP-01 | iOS | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-AND-01 | SP-01 | Android | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-IOS-02 | SP-02 | iOS | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-AND-02 | SP-02 | Android | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-IOS-03 | SP-03 | iOS | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-AND-03 | SP-03 | Android | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-IOS-04 | SP-04 | iOS | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-AND-04 | SP-04 | Android | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-IOS-05 | SP-05 | iOS | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-AND-05 | SP-05 | Android | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-IOS-06 | SP-06 | iOS | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-AND-06 | SP-06 | Android | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-IOS-07 | SP-07 | iOS | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-AND-07 | SP-07 | Android | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-IOS-08 | SP-08 | iOS | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-AND-08 | SP-08 | Android | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-IOS-09 | SP-09 | iOS | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-AND-09 | SP-09 | Android | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-IOS-10 | SP-10 | iOS | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-AND-10 | SP-10 | Android | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-IOS-11 | SP-11 | iOS | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-AND-11 | SP-11 | Android | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-IOS-12 | SP-12 | iOS | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-AND-12 | SP-12 | Android | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-IOS-13 | SP-13 | iOS | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-AND-13 | SP-13 | Android | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-IOS-14 | SP-14 | iOS | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-AND-14 | SP-14 | Android | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-IOS-15 | SP-15 | iOS | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-AND-15 | SP-15 | Android | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-IOS-16 | SP-16 | iOS | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-AND-16 | SP-16 | Android | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-IOS-17 | SP-17 | iOS | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-AND-17 | SP-17 | Android | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-IOS-18 | SP-18 | iOS | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
| SPR-AND-18 | SP-18 | Android | NOT RUN | TBD | TBD | TBD | — | — | — | — | — | — |
