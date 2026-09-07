---
name: release-verification
description: Performs final evidence-based verification before a change is considered ready for pull request, merge, or deployment.
---

# Release Verification

Use this skill after implementation and review, before declaring a task ready for pull request, merge, or deployment.

## Goal

Confirm with concrete evidence that the completed change satisfies its requirements, passes the required technical checks, contains no unrelated work, and has no known material blocker.

## Workflow

### 1. Re-read the task

Confirm:

- goal;
- scope;
- acceptance criteria;
- expected behavior;
- known risks;
- required manual verification.

Do not verify only against the implementation.

Verify against the original task.

### 2. Inspect the final Git state

Check:

- current branch;
- changed files;
- staged files when relevant;
- final diff;
- unrelated changes;
- temporary files;
- debug code.

Do not discard unrelated user work.

Do not include unrelated changes in the task.

### 3. Verify automated tests

Run the tests appropriate to the change.

Use progressive verification:

targeted tests
→ affected feature suite
→ broader regression suite when justified

Do not report a suite as passing unless it was actually run successfully.

### 4. Verify static quality checks

Run relevant checks such as:

- type checking;
- linting;
- build;
- import/startup validation.

Treat existing unrelated warnings separately from new failures.

Do not hide or suppress new errors merely to obtain a green result.

### 5. Verify database state

When database changes are involved, verify:

- current Alembic revision;
- expected head;
- migration upgrade;
- model/schema consistency;
- relevant persistence tests;
- data-integrity assumptions.

Use the `database-migration` skill for migration-specific work.

### 6. Verify API contracts

When API behavior changed, confirm:

- request shape;
- response shape;
- status codes;
- errors;
- authentication;
- ownership;
- client compatibility.

Use the `api-contract` skill when needed.

### 7. Verify user-facing behavior

For UI or workflow changes, define and execute the required manual E2E scenarios when possible.

Verify relevant:

- navigation;
- loading;
- empty state;
- error state;
- success behavior;
- mutation feedback;
- cache refresh;
- destructive-action confirmation.

Do not claim manual E2E passed unless it was actually performed.

### 8. Confirm review status

Verify that:

- material code-review findings were evaluated;
- confirmed findings were fixed;
- relevant QA findings were addressed;
- security review was performed when required;
- no known HIGH or CRITICAL issue remains.

Reviewer findings are not automatically correct; only validated material findings block completion.

### 9. Check change isolation

Confirm:

- all changed files belong to the task;
- no unrelated refactor is included;
- no secrets are present;
- no temporary artifacts remain;
- no generated files are accidentally included;
- no development-only workaround leaked into production code.

### 10. Identify remaining uncertainty

Explicitly report anything not verified, for example:

- physical-device E2E not run;
- external service unavailable;
- production credentials unavailable;
- migration downgrade not tested;
- platform-specific behavior not verified.

Unverified work must not be described as verified.

### 11. Determine readiness

Classify the result as:

READY
- required checks pass;
- acceptance criteria are satisfied;
- no known material blocker remains.

READY WITH MANUAL CHECK
- automated verification passes;
- a clearly identified non-blocking manual check remains.

NOT READY
- material test failure;
- missing required verification;
- unresolved correctness/security/data-integrity issue;
- acceptance criterion not satisfied.

### 12. Final report

Return a concise verification summary:

- task;
- checks run;
- results;
- manual verification;
- remaining risks;
- readiness status.

Never declare READY without evidence.