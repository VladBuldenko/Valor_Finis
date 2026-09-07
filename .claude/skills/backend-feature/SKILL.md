---
name: backend-feature
description: Implements backend features using the repository's existing architecture, business rules, validation, persistence patterns, and test strategy.
---

# Backend Feature

Use this skill when implementing or modifying backend application behavior.

## Goal

Deliver the smallest complete backend change while preserving existing architecture, contracts, data integrity, ownership rules, and test coverage.

## Workflow

### 1. Inspect before editing

Read the relevant:

- router or endpoint;
- schemas;
- service;
- repository;
- database model;
- related tests;
- exception handling;
- authentication and ownership logic.

Search for similar existing features before introducing a new pattern.

Do not guess repository structure.

### 2. Define the behavior

Identify:

- input;
- output;
- business rules;
- validation;
- ownership requirements;
- expected errors;
- persistence changes;
- compatibility requirements.

Separate business logic from transport and persistence concerns.

### 3. Preserve layer boundaries

Follow the existing flow:

Router
→ Service
→ Repository
→ Database

Router responsibilities:

- HTTP concerns;
- dependency injection;
- request/response schemas;
- translating domain errors into API responses when required.

Service responsibilities:

- business rules;
- orchestration;
- authorization decisions when part of domain behavior;
- coordination between repositories or services.

Repository responsibilities:

- queries;
- persistence;
- ownership-scoped data access;
- database-specific operations.

Do not place business logic directly in routers or repositories unless the repository pattern already requires it.

### 4. Implement validation correctly

Validate at the appropriate boundary.

Use schemas for structural input validation.

Use services for business validation.

Use database constraints for invariants that must remain correct under concurrency.

Do not rely only on application-level checks when the database must guarantee integrity.

### 5. Preserve ownership and security

For user-owned resources:

- never trust a client-provided user ID;
- use authenticated user context;
- scope reads and mutations by owner;
- prevent cross-user access;
- return repository/project-standard not-found or authorization behavior.

### 6. Preserve data integrity

When changing stored data:

- preserve existing foreign-key relationships;
- avoid destructive changes unless explicitly required;
- consider concurrency;
- use transactions appropriately;
- maintain Decimal/money precision where relevant;
- avoid silent data loss.

If the change requires a schema modification, use the `database-migration` skill.

### 7. Maintain API contracts

Do not change existing request or response behavior unintentionally.

When an API contract changes:

- update schemas;
- update relevant tests;
- verify existing clients;
- use the `api-contract` skill when the change is significant.

### 8. Add tests

Add or update relevant tests for:

- happy path;
- validation;
- ownership;
- not-found behavior;
- business rules;
- persistence;
- regression cases.

Use integration tests when behavior depends on real database semantics.

Do not mock away behavior that the test is intended to verify.

### 9. Verify progressively

Run focused tests first.

Then run broader relevant backend tests.

When applicable verify:

- targeted pytest suite;
- full backend pytest suite;
- migration state;
- application import/startup;
- API behavior.

Do not claim success unless the checks were actually run.

### 10. Final check

Before completion verify:

- behavior matches requirements;
- no unrelated refactor was introduced;
- architecture boundaries remain intact;
- ownership is preserved;
- tests cover material behavior;
- no temporary/debug code remains.

Report what changed and exactly which checks passed.