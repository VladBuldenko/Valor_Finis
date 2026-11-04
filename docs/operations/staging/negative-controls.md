# Negative Controls (VF-QA-1)

A negative control breaks ONE guard in the source (a scripted, temporary, single-pattern edit that is always restored) and expects at
least one test to fail. Each control ends in exactly one class:

| Class | Meaning | Counted as a caught control? |
|---|---|---|
| CAUGHT | A test failed because of the broken guard (a mutant that does not even load is not this class) | yes |
| EQUIVALENT | The edit does not change behaviour: another layer enforces the same refusal | **no** |
| INVALID | The edit did not apply or the program did not load | **no** |
| SURVIVED | Tests still pass although a guard is broken | no, and a defect of the tests |

Run on 2026-11-04 against the local branch after the post-review corrections (script kept in the task scratchpad, not committed).
Result: **96 controls, 95 caught, 1 equivalent, 0 invalid, 0 surviving.**

The first run of this set had two survivors. M20 is equivalent (below). N24 (a superuser application role accepted by the SQL check) survived
because the test only looked for the row's *name* in the output, which is always printed; the assertion now requires the row's status to be
`FAIL`, and N24 is caught. The same weakness was removed from two neighbouring assertions.

## Equivalent mutant (retained, not counted)

**M20, "accept a comma in the host list".** The guard `if not host or "," in host or host.startswith("/")` was reduced to `if not host`.
Tests still pass because a comma host is refused with the same code by three other paths: the single-host URL parsing, the host
normalizer and the allowlist comparison. `%2C`, `host=`, `hostaddr=`, `dbname=` and a repeated `sslmode` are refused as well. No behaviour
differs, so no test can fail; it is reported separately from the caught controls.

## Controls added by the post-review corrections (N01 to N31)

| ID | Broken guard | Caught by |
|---|---|---|
| N01 | reset preflight of external dependents skipped | unit |
| N02 | destroy uses `CASCADE` instead of `RESTRICT` | unit (no executable string may contain `CASCADE`) |
| N03 | in-transaction external dependency check removed | real database |
| N04 | out-of-scope fingerprint gate removed | real database (partition, statistics, public partition of an external parent) |
| N05 | `ACCESS EXCLUSIVE` table locks removed | real database (concurrent DDL) |
| N06 | undroppable objects ignored | real database (dependency cycle) |
| N07 | automatic dependencies ignored by the dependent query | real database |
| N08 | unattributable dependency classes treated as in scope | real database (operator scenario) |
| N09 | fingerprint ignores every out-of-scope relation | real database |
| N10 | rolled-back destroy refusals reported as changed | unit |
| N11 | seed lock acquisition result ignored | real database |
| N12 | seed lock liveness never checked | real database (lock released while the connection lives) |
| N13 | seed does not take the lock | unit |
| N14 | lock not re-checked before each step | real database |
| N15 | categories left out of owned-data detection | real database |
| N16 | default categories counted as owned data | real database |
| N17 | owner-consistency evidence not recorded | real database |
| N18 | seed stop after the first write reported as a refusal | real database |
| N19 to N23 | operator runner: `require` accepted on a remote host, parity disclaimer dropped, `DATABASE_URL` accepted, non-staging database accepted, revision not required | real database |
| N24 to N28 | A1 SQL: superuser role, `PUBLIC` privileges, revision, `PUBLIC` CREATE on `public`, `DELETE` privilege | real database |
| N29 to N31 | B1: application relations and functions ignored, application database accepted | real database |

M01 to M19 and M21 to M65 are the controls of the original implementation (identity guard, bootstrap, binding, reset confirmation, seed,
redaction, Supabase probe, command line, Alembic hook); M42, M43, M45 to M47 and M63 to M64 need the real database to be caught.
Two of them were re-targeted because the code they patch changed: M43 now targets the owned-data detection, M46 the owner-consistency
check.

## What these controls do not show

They show that the guards the tests exercise cannot be removed unnoticed. They do not show that the guards are sufficient (see the
residual risks in the runbook, section 12), and they were run against a local PostgreSQL 18 only.
