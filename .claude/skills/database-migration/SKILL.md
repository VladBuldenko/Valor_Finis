---
name: database-migration
description: Designs, implements, and verifies safe database schema migrations with attention to backward compatibility, data integrity, concurrency, and rollback risk.
---

# Database Migration

Use this skill whenever a task changes database structure, constraints, indexes, stored defaults, or persisted data shape.

## Goal

Make the smallest safe schema change while preserving existing data, relationships, application compatibility, and migration correctness.

## Workflow

### 1. Inspect current database state

Before writing a migration, inspect:

- current SQLAlchemy models;
- relevant repositories and services;
- existing Alembic migrations;
- foreign keys;
- unique constraints;
- indexes;
- nullable/default behavior;
- existing data assumptions;
- current Alembic head.

Do not guess the current schema.

### 2. Define the migration contract

Identify:

- what schema change is required;
- why it is required;
- whether existing rows are affected;
- whether backfill is required;
- whether the change is reversible;
- what application code depends on the old schema;
- whether the migration must support zero-downtime or staged deployment.

Separate schema changes from business-logic changes.

### 3. Prefer additive changes

When possible, prefer:

- new nullable columns first;
- new indexes;
- new tables;
- new constraints after data is valid;
- staged tightening of nullability.

Avoid destructive operations unless the task explicitly requires them.

Do not drop columns, tables, or data without explicit justification.

### 4. Preserve existing data

For existing rows:

- define deterministic defaults or backfill behavior;
- preserve IDs and foreign-key relationships;
- avoid rewriting data unnecessarily;
- avoid changing semantic meaning silently;
- verify that existing rows remain valid after the migration.

If data transformation is required, make it explicit and testable.

### 5. Handle constraints carefully

For unique constraints and invariants:

- inspect existing data for conflicts;
- ensure the constraint matches business semantics;
- consider concurrent writes;
- prefer database-enforced guarantees for invariants that must survive race conditions.

Do not rely only on application-level pre-checks when concurrency can violate correctness.

### 6. Handle indexes intentionally

Add indexes only when justified by:

- lookup patterns;
- ownership filters;
- joins;
- ordering;
- uniqueness;
- measured or obvious query need.

Avoid speculative indexes.

Consider write cost and index size.

### 7. Preserve compatibility

Check whether the migration changes:

- API behavior;
- request/response schemas;
- repository queries;
- default values;
- application startup;
- old code compatibility.

When relevant, design migrations so old and new application versions can coexist during deployment.

### 8. Write Alembic migration correctly

Use explicit upgrade and downgrade logic where safe.

The migration should:

- have the correct `down_revision`;
- use deterministic operations;
- avoid environment-specific assumptions;
- avoid depending on application runtime state when possible;
- avoid irreversible data destruction unless explicitly accepted.

If downgrade cannot safely restore data, document that limitation.

### 9. Verify migration execution

Run:

- `alembic current`;
- `alembic heads`;
- `alembic upgrade head`.

When reasonable also verify downgrade/upgrade on a disposable database.

Confirm there is exactly one intended head unless the project intentionally uses multiple heads.

### 10. Verify application behavior after migration

Run relevant:

- repository tests;
- service tests;
- integration tests;
- full backend regression suite when justified.

Confirm the application still reads and writes affected data correctly.

### 11. Check production safety

Before completion, ask:

- Can this lock a large table?
- Can this fail because of existing rows?
- Can concurrent requests violate the new invariant?
- Can old application code break during rollout?
- Can the migration lose or reinterpret data?
- Is rollback realistic?

Only escalate issues that are relevant to the actual schema and deployment model.

### 12. Final verification

Before completion verify:

- migration is at the expected head;
- models and schema agree;
- constraints match business rules;
- existing data is preserved;
- foreign keys remain valid;
- required tests pass;
- no unrelated schema changes are included.

Report exactly what changed and which migration checks were actually run.