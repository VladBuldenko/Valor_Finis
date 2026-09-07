---
name: bugfix-debugging
description: Diagnoses reproducible defects, identifies root cause, adds regression coverage, applies the smallest correct fix, and verifies that related behavior still works.
---

# Bugfix Debugging

Use this skill when fixing a bug, regression, incorrect behavior, flaky behavior, or production defect.

## Goal

Find the real root cause, fix it with the smallest safe change, and add evidence that prevents the same defect from returning.

## Workflow

### 1. Define the failure precisely

Before changing code, identify:

- expected behavior;
- actual behavior;
- where the failure is observed;
- reproducible steps;
- environment or conditions required;
- whether the issue is deterministic or intermittent.

Do not start with a guessed fix.

### 2. Reproduce the bug

Try to reproduce the problem using the smallest reliable scenario.

Prefer:

- an existing failing test;
- a focused new regression test;
- a deterministic local reproduction;
- logs or concrete runtime evidence.

If the bug cannot be reproduced, state what evidence is available and what remains uncertain.

### 3. Inspect the relevant code path

Trace the behavior through the actual implementation.

Inspect:

- entry point;
- validation;
- business logic;
- state transitions;
- persistence;
- API boundaries;
- client behavior;
- related tests.

Do not fix only the visible symptom without understanding the code path.

### 4. Identify the root cause

Distinguish:

- root cause;
- secondary symptoms;
- unrelated weaknesses.

Ask:

- where does behavior first become incorrect?
- which invariant is violated?
- why did existing tests not catch it?
- is the issue local or systemic?

Do not expand the scope unless the same root cause clearly affects multiple paths.

### 5. Assess risk before fixing

Check whether the bug touches:

- authentication or authorization;
- ownership;
- destructive operations;
- database integrity;
- concurrency;
- migrations;
- public API contracts;
- cache/state invalidation;
- external services.

Use specialized review when the risk justifies it.

### 6. Add regression coverage

When practical, add a test that reproduces the broken behavior.

The regression test should:

- fail for the broken behavior;
- pass after the fix;
- assert user-visible or system-visible behavior;
- avoid unnecessary coupling to implementation details.

Do not temporarily corrupt correct production code solely to prove the test fails.

### 7. Implement the smallest correct fix

Fix the root cause, not just the symptom.

Prefer:

- local changes;
- existing abstractions;
- existing patterns;
- explicit behavior.

Avoid:

- unrelated refactoring;
- broad rewrites;
- new abstractions without need;
- suppressing errors instead of fixing them;
- weakening validation to make the failure disappear.

### 8. Verify the direct fix

Run the smallest relevant verification first.

Examples:

- new regression test;
- affected unit test;
- affected integration test;
- typecheck;
- focused manual reproduction.

Confirm the original failure is resolved.

### 9. Verify regressions

Run broader checks appropriate to the affected area.

Examples:

- related feature suite;
- backend regression suite;
- mobile typecheck/lint;
- API integration tests;
- manual E2E.

Do not assume a local fix is safe without checking nearby behavior.

### 10. Check for hidden side effects

Before completion inspect:

- changed files;
- state/cache invalidation;
- error behavior;
- ownership behavior;
- persisted data;
- API compatibility;
- navigation behavior;
- logging/debug artifacts.

Remove temporary diagnostics that should not remain.

### 11. Confirm the bug cannot recur through the same path

Ask:

- Does the new test protect the root cause?
- Is there another equivalent code path still broken?
- Was an invariant only patched in one place?
- Is the fix dependent on timing or incidental behavior?

Only broaden the fix when repository evidence shows the same root cause elsewhere.

### 12. Final report

Report concisely:

- root cause;
- fix;
- regression coverage;
- checks run;
- anything still unverified.

Do not report the bug as fixed without evidence.
