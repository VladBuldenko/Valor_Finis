---
name: test-feature
description: Designs, writes, and verifies meaningful automated tests for new behavior, regressions, edge cases, ownership, persistence, and API contracts without changing production behavior merely to satisfy tests.
---

# Test Feature

Use this skill when adding or strengthening automated test coverage for a feature, bug fix, regression, API contract, repository behavior, or business rule.

## Goal

Create tests that prove meaningful behavior, catch regressions, and validate real system guarantees instead of only increasing test count.

## Workflow

### 1. Understand what must be proven

Before writing tests, identify:

- required behavior;
- acceptance criteria;
- business rules;
- error behavior;
- ownership rules;
- persistence behavior;
- concurrency risks;
- regression risks.

Do not start from implementation details alone.

### 2. Inspect existing tests

Read:

- nearby unit tests;
- integration tests;
- fixtures;
- factories;
- database setup;
- mocking conventions;
- naming conventions;
- assertion style.

Reuse existing patterns unless they are insufficient for the behavior being tested.

### 3. Choose the correct test level

Use unit tests for isolated behavior such as:

- service business rules;
- validation;
- transformation logic;
- deterministic repository behavior where database semantics are not essential.

Use integration tests when behavior depends on:

- real PostgreSQL constraints;
- transactions;
- foreign keys;
- uniqueness;
- concurrency;
- FastAPI request/response behavior;
- authentication/ownership integration;
- Alembic schema.

Do not mock away the exact behavior the test is supposed to verify.

### 4. Test behavior, not implementation details

Prefer assertions about:

- returned values;
- persisted state;
- status codes;
- errors;
- ownership boundaries;
- observable side effects.

Avoid tests that fail only because internal method ordering or private implementation changed.

### 5. Cover the happy path

Verify that the intended primary behavior succeeds.

Assert meaningful output, not only that "no exception happened."

### 6. Cover failure paths

When relevant, test:

- invalid input;
- not found;
- unauthorized or cross-user access;
- duplicate/conflicting data;
- failed persistence;
- unsupported state transitions;
- destructive actions;
- external dependency failure.

Expected failures should be explicit.

### 7. Cover ownership

For user-owned resources, verify at least when relevant:

- owner can read/change the resource;
- another user cannot access it;
- client-supplied ownership data cannot bypass server ownership rules.

### 8. Cover regressions

When fixing a bug:

1. reproduce the bug in a test;
2. verify the test would fail for the broken behavior;
3. implement the smallest fix;
4. verify the test passes afterward.

Do not intentionally break correct production code merely to prove the test can fail.

If historical broken behavior cannot be safely reproduced, explain the evidence used instead.

### 9. Test concurrency with real database semantics

When correctness depends on race conditions:

- use independent database sessions;
- coordinate concurrent execution deterministically where possible;
- verify the final database state;
- verify no request leaks an unexpected integrity error;
- avoid flaky timing-only tests based on arbitrary sleeps.

Use PostgreSQL integration tests for PostgreSQL-specific guarantees.

### 10. Keep tests deterministic

Tests should not depend on:

- execution order;
- local timezone unless intentional;
- arbitrary sleep timing;
- external network access;
- shared mutable global state;
- random values without control.

Prefer deterministic fixtures and explicit setup.

### 11. Keep test scope isolated

Each test should prove one coherent behavior.

Avoid giant tests that verify unrelated features at once.

Do not duplicate the same assertion across many layers without a reason.

### 12. Verify progressively

Run:

- the new or modified test first;
- the relevant test module;
- the relevant feature suite;
- broader regression suite when justified.

For backend changes, prefer the real project database configuration required by the repository.

Never claim a suite passed unless it was actually run.

### 13. Evaluate coverage quality

Before completion ask:

- Would this test catch the bug or regression we care about?
- Does it test the real guarantee?
- Is an important failure case missing?
- Is the test too coupled to implementation?
- Could it pass while production behavior is still wrong?

Do not use test count as a quality metric by itself.

### 14. Final check

Before completion verify:

- tests match requirements;
- important failure paths are covered;
- ownership is covered where relevant;
- concurrency uses appropriate integration testing;
- tests are deterministic;
- production code was not distorted for test convenience;
- relevant suites pass.

Report exactly which tests were added or changed and which commands were actually run.