# Rule and alert dispatcher (VF-020E10) - architecture decision and operations

Status: implemented on the local feature branch `feat/VF-020E10-periodic-dispatcher`; NOT pushed, merged,
deployed or scheduled. **No Render service exists or is created by this change.** Until a scheduler is
deployed AND verified, AUTO and alert detection remain "executed at the next user-triggered drain" and must
not be described as guaranteed unattended (P50).

## 1. Architecture decision record

**Decision.** A separate, finite Python process, `python -m app.modules.financial_rules.dispatcher`, run by a
Render Cron Job (`*/10 * * * *`, the boundary approved by P87). It never runs inside the FastAPI web process and
adds no HTTP endpoint (no public cross-user dispatcher API).

**Why no migration.** The durable queue, leases, retries, execution uniqueness and alert uniqueness already
live in `financial_events`, `rule_executions` and `rule_alerts` (E2, E6, E9A). The dispatcher only chooses which
users to serve. No cursor/state table was added. Event fairness comes from ordering by head age (a served user's
head advances, so progress is intrinsic). Alert-user fairness has NO persistent progress marker, so it is
probabilistic when the population exceeds one pass - see section 1a for the exact guarantee and the migration gate
for a deterministic one.

**Reuse vs new code.**

| Concern | Source |
|---|---|
| claim / lease / retry / dead, strict FIFO, L0, atomic processing | reused: `financial_event_processor.drain_user_events` (E7) |
| AUTO and CONFIRM evaluation, holds, lazy expiry at dispatch | reused: `rule_execution_service.process_event` (E7/E8) |
| alert episodes, Budget levels, deduplication, failure flag | reused: `rule_alert_service.evaluate_user_alerts_best_effort` (E9B) |
| cross-user event discovery | new: `financial_event_queue_repository.discover_users_with_progressing_head` |
| cross-user alert-user discovery | new: `rule_alert_repository.count_users_with_enabled_alert_rules` / `get_users_with_enabled_alert_rules_page` |
| bounded pass, config, summary, exit codes | new: `financial_rules/dispatcher.py` |

**Event discovery.** One SQL statement over `financial_events` only (never Income): `DISTINCT ON (user_id)`
selects each user's FIFO head over ALL unfinished, non-business-deferred events in `(occurred_at, id)` order
(partial FIFO index), and only THEN keeps heads that are claimable now (`pending`; `failed_retryable` with
`next_attempt_at <= now()`; `processing` with an expired lease). A user whose head is under a live lease or
waiting for its retry is not returned, so a newer event cannot bypass it and no slot is wasted. An expired
sixth-attempt lease is returned and the existing claim path turns it into `dead` (never a seventh attempt).
Fairness: the result is ordered by head age, oldest first, and serving a user advances or removes its head, so
a fixed batch cannot starve users beyond the first page across runs.

**Locking and concurrency.** The dispatcher holds no lock of its own. Each user is drained in a fresh session by
the existing per-user drain, which takes the user lock L0 and claims with a token and lease, so two dispatchers,
a user-triggered `POST /financial-rules/evaluate`, the best-effort post-Income drain, and a run cancelled by a
manual Render trigger are all safe: the second worker sees a live lease or a processed event and does nothing, and
a cancelled run's lease simply expires. Render's single-active-run guarantee is therefore not relied upon.

**Alerts.** Users with at least one ENABLED floor, overcommitment or Budget alert rule are evaluated every pass,
even without events. At most `RULE_DISPATCHER_MAX_ALERT_USERS` users are evaluated per pass, chosen as a per-run random
sample (ordered by `md5(user_id || fresh per-run seed)`; no cursor, no clock). See section 1a for what this does and
does not guarantee.
A missing `rule_alerts` table is reported as `alerts_unavailable` and is NOT a failure; a real evaluation or
discovery error is `alert_failures` and makes the run exit 3. A missing table never blocks event processing.

**CONFIRM expiry.** Evidence from E8: hold queries filter `expires_at > now()`, so an expired proposal stops
holding capacity at the instant it expires; stored state is normalized to `expired` lazily at read, confirm,
reject and event dispatch (which the dispatcher triggers for every user with events). No separate expiry job or
schema was added; confirmation still revalidates in full.

### 1a. Alert-user liveness: what is guaranteed, and the migration gate

*Finding (reproduced on the first E10 design).* Selecting a page by `floor(time / interval) % pages` over a fixed
user order cannot give liveness without stored progress: with 6 alert users and every run interrupted after two
users, only the same first two users were EVER evaluated (2 of 6 after 10 runs); and when the real cadence was a
multiple of the configured interval, the same single page was visited forever (2 of 6). Full-page tests and a
stable cadence hid both.

*Current behaviour (no schema change).* Each run orders the enabled-alert users by `md5(user_id || fresh random
seed)` and evaluates a prefix up to the cap and the time budget. There is no page index and no dependence on the
clock, so skipped, delayed or doubled ticks change nothing and an interrupted run evaluated a uniformly random
subset, not a fixed prefix.

| Situation | Guarantee |
|---|---|
| enabled-alert users <= `RULE_DISPATCHER_MAX_ALERT_USERS` and the pass is not cut by the time budget and no alert failure trips the consecutive-failure breaker | **every user is evaluated in every run** (hard) |
| more users than one pass can evaluate, or passes that are cut early | **almost-sure coverage, no deterministic bound**: after `k` runs a given user is still unvisited with probability about `(1 - n/M)^k` (`n` evaluated per run, `M` users), independent of cadence |
| a run that crashes or is cancelled | the sample is simply different next run; nothing is lost |

`alert_users_total` and `alert_users_truncated` expose when the population exceeds one pass, so operators can see
the moment the probabilistic regime begins.

*Why a deterministic bound needs persistent state, and the gate.* A hard bound ("every user within `ceil(M/n)`
completed runs, however runs are cut or missed") requires remembering who was evaluated. That means a new
table (for example `rule_alert_evaluation_state(user_id uuid primary key, last_evaluated_at timestamptz not
null)`, written by the dispatcher after each evaluation and read as "least recently evaluated first"). That is
production DDL and is **NOT part of this change**. If it is wanted, it is a separate stage with its own gates:
(1) architecture decision recorded here, (2) additive migration with the Data API REVOKE pattern and an
expand-first runtime (use the table only when it exists, otherwise fall back to the random sample), (3) the usual
authorization sequence (read-only preflight, backup, exact-revision migration, post-checks) and (4) tests for
cut/missed/doubled runs against the deterministic bound. Until then the probabilistic guarantee above is the
accurate statement; do not describe alert coverage as guaranteed fair beyond the first row of the table.

### 1b. Persistent progress: schema stage and rollout order

Migration `c4d8a2f6e193` (down_revision `a7c3e91d5b24`) creates `alert_dispatch_progress` and the sequence
`alert_dispatch_service_seq` (column contract in `docs/database-schema.md`). It is additive: no existing table is
read, locked or changed, there is no backfill, and the deployed runtime ignores it. It is a SEPARATE change from the
runtime that uses it, and the schema must be merged and applied before the deterministic runtime is activated.

Exact order (nothing below has been executed): (1) verify the Render database connection; (2) verify E9A
`a7c3e91d5b24` is applied and healthy; (3) obtain a separate authorization naming `c4d8a2f6e193`; (4) read-only
preflight (revision exactly `a7c3e91d5b24`, table and sequence absent) and a verified backup; (5) apply
`alembic upgrade c4d8a2f6e193` with a transaction-local `lock_timeout` (no existing relation is locked); (6) verify the
table, six columns, four constraints, the index, the sequence and that the Data API roles hold no privilege on either;
(7) deploy the runtime only after a separate approval; (8) observe a scheduled run report
`alert_selection: progress` and verify coverage before describing alert evaluation as deterministic.

Rollback assumptions: the runtime falls back to the random sample while the table is absent, so
`alembic downgrade a7c3e91d5b24` (or `RULE_DISPATCHER_ALERT_PROGRESS=off`) is safe at any time; the only loss is the
service order, which rebuilds itself.

## 2. Process contract

Environment (all optional, validated before any work; invalid -> exit 2):

| Variable | Default | Range | Meaning |
|---|---|---|---|
| `RULE_DISPATCHER_ENABLED` | `true` | true/false | operational switch; `false` exits 0 without touching the database |
| `RULE_DISPATCHER_MAX_USERS` | 50 | 1-1000 | users drained per pass |
| `RULE_DISPATCHER_MAX_EVENTS_PER_USER` | 20 | 1-100 | events per user per pass (same cap as the evaluate endpoint) |
| `RULE_DISPATCHER_MAX_ALERT_USERS` | 200 | 1-5000 | alert users evaluated per pass (a random sample when more users have enabled alert rules) |
| `RULE_DISPATCHER_TIME_BUDGET_SECONDS` | 240 | 5-3300 | stop starting new users after this; the last fifth of the budget is reserved for alert evaluation; remaining work waits for the next run |

Defaults come from the contract (per-user cap = evaluate default) and from finishing well inside a 10-minute
tick; they are not an SLA. Re-derive them from measured run times after the first production runs.

The process also needs the same application settings as the web service (`DATABASE_URL`, `AUTH_MODE` and, for
`supabase` mode, the Supabase variables; the dispatcher never authenticates a user). It exits when the pass ends.

Exit codes: `0` success / no-op / disabled / time budget reached; `1` fatal infrastructure (event discovery
failed, three consecutive connection or unrecorded-failure users, or three consecutive alert failures); `2` invalid configuration; `3` completed with failures (user
failure, retryable-failed or dead events, alert failure). The last stdout line is
`dispatcher_summary {json}` with only counters: `outcome, users_considered, users_processed, events_processed,
events_deferred, events_failed_retryable, events_dead, events_unrecorded_failures, users_blocked, user_failures, alert_users_considered,
alert_users_total, alert_users_evaluated, alerts_created, alerts_resolved, alert_failures, alerts_unavailable, alert_users_truncated, budget_exhausted,
execution_outcomes, elapsed_seconds`. Logs use a short hash of the user id and never contain the database URL,
secrets, tokens, amounts or names.

## 3. Render Cron Job proposal (NOT created)

Verified in Render's current documentation: Docker-based cron jobs are supported (the image is pulled before every
run and the Docker Command overrides the Dockerfile `CMD`); the schedule is a standard cron expression evaluated in
UTC; a run is stopped after 12 hours; at most one run of a cron job is active (a due run waits for the active one),
and a manual "Trigger Run" cancels the active run and starts a new one; billing is by compute plan, prorated per
second of run time, with a $1 minimum per cron job per month; Blueprint type `cron` needs `name`, `runtime`,
`schedule`; the smallest cron plan is `0.5c-512mb`. NOT stated in the pages read (verify in the dashboard before
relying on them): how exit codes map to run status, failed-run notifications, and how to suspend a cron job.

Proposed settings (create only after the release decision in section 5):

```
Service type:   Cron Job            Region: same region as the web service / database
Runtime:        Docker              Dockerfile: services/api/Dockerfile   Docker context: services/api
Docker Command: python -m app.modules.financial_rules.dispatcher
Schedule:       */10 * * * *        (UTC)
Plan:           smallest available (the pass is sequential; start at 0.5c-512mb and measure)
Auto-deploy:    follow the same branch/commit policy as the API
Environment:    DATABASE_URL, AUTH_MODE, (SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY for supabase mode) - same
                values/secret source as the web service; plus the optional RULE_DISPATCHER_* variables.
```

The Dockerfile works as is (`WORKDIR /app` holds the `services/api` tree, so `python -m ...` resolves). The image
includes Tesseract and is pulled on every run, which adds start-up time and is the main cost driver; a slimmer
dispatcher image is a possible later optimization, not required for correctness.

Blueprint fragment for reference only (do not commit a `render.yaml` that provisions it automatically):

```yaml
- type: cron
  name: valor-rule-dispatcher
  runtime: docker
  dockerfilePath: ./services/api/Dockerfile
  dockerContext: ./services/api
  dockerCommand: python -m app.modules.financial_rules.dispatcher
  schedule: "*/10 * * * *"
  envVars:
    - key: DATABASE_URL
      sync: false
```

Database connections: the pass is sequential, one short session at a time (SQLAlchemy default pool, disposed at
exit), so it needs one connection at a time on top of the web service. Use the same connection URL and pooler
mode as the web service (the code already works with it; L0 is a transaction-scoped advisory lock, so it does not
need session-level pooling). Do not change pooler mode for the dispatcher without re-running the concurrency
tests against it, and confirm the Supabase plan's connection limit covers web + cron.

## 4. Operations

**Verify one scheduled run.** Dashboard -> the cron job -> Runs: the run finished, exit code 0, and the log's last
line is `dispatcher_summary` with `outcome` `success` or `noop`. Then check, read-only:
`SELECT status, count(*) FROM financial_events GROUP BY status;` (no growing `pending`).

**Detect problems.**
- Failed run: the process exits non-zero (1 infra, 2 config, 3 completed with failures) and logs an `ERROR dispatcher_summary` line. How Render displays a non-zero exit is not documented in the pages read: verify it on the first deployment and, if needed, monitor the `ERROR` log line instead.
- Persistent backlog: the oldest unfinished, due event keeps ageing:
  `SELECT min(occurred_at) FROM financial_events WHERE status IN ('pending','processing','failed_retryable') AND (not_before IS NULL OR not_before <= now());`
  alert when it is older than about 3 x the schedule (30 minutes).
- Dead events: `SELECT count(*) FROM financial_events WHERE status = 'dead';` any non-zero value needs the runbook
  (inspect `last_error_code`; re-queue is a separate manual decision). The run that creates one exits 3.
- Recurring database errors: repeated exit 1 or `user_failures > 0` with the same user hash.
- Missing alert storage: `alerts_unavailable: true` in the summary means the E9A table is absent; it is expected only
  before the E9A production migration.

**Disable safely.** Preferred: set `RULE_DISPATCHER_ENABLED=false` on the cron job (the next run exits 0 touching
nothing); alternatively suspend the service in the dashboard (confirm the control exists on your plan). Pending
events stay durable and are still processed by user-triggered drains.

**Rollback.** Disable as above (or delete the cron service). No schema or data change needs reverting: processed
events, executions and alerts are ordinary committed rows; a half-done run leaves only expiring leases.

**Verify idempotency after deployment.** (1) Trigger two runs back to back: the second reports `noop` /
`events_processed: 0`. (2) `SELECT user_id, rule_id, source_id, count(*) FROM rule_executions GROUP BY 1,2,3 HAVING count(*) > 1;`
returns no rows. (3) `SELECT user_id, rule_type, subject_id, period_key, level, count(*) FROM rule_alerts GROUP BY 1,2,3,4,5 HAVING count(*) > 1;`
returns no rows. (4) `alerts_created` is 0 on a repeated run with unchanged state.

## 5. Release dependencies (all must be independently verified; none is assumed)

1. Render database connectivity restored (authenticated Account reads previously returned HTTP 500).
2. Production Alembic revision equals `a7c3e91d5b24` (E9A applied; separate authorizations A/B/C).
3. E9A schema, constraints and privileges verified (read-only post-check).
4. E9B runtime deployed and healthy.
5. The cron configuration is supported by the Render account and any additional cost is approved.
6. Tests and security review pass for the deployed commit.
7. Explicit authorization to create/enable the cron job.

Only after a successful, verified scheduled run may AUTO and alerts be described as running unattended.

## 6. Residual risks and deferred work

- Expense, Transfer and adjustment writes still do not trigger an alert evaluation themselves; the dispatcher
  detects them within one tick.
- Alert-user coverage is almost-sure, not bounded, once enabled-alert users exceed one pass (section 1a). Watch
  `alert_users_truncated`; a deterministic bound needs the persistent-progress migration described there.
- A manual "Trigger Run" cancels an active run mid-pass; the event it was draining is recovered by lease expiry
  (up to 5 minutes) - correct but briefly delayed for that user.
- Exit-code and notification behaviour of Render cron runs is not documented in the pages read; verify in the
  dashboard.
- The Docker image is heavier than the dispatcher needs (Tesseract); optimization is deferred.
