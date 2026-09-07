---
name: api-contract
description: Designs and verifies API request/response contracts, validation, error behavior, compatibility, and client consistency.
---

# API Contract

Use this skill whenever a task creates or changes an API endpoint, request schema, response schema, error behavior, or client/backend contract.

## Goal

Keep the API predictable, backward-compatible where possible, explicit, testable, and consistent across backend and clients.

## Workflow

### 1. Inspect the current contract

Before changing anything, inspect:

- route definitions;
- request schemas;
- response schemas;
- status codes;
- error responses;
- authentication requirements;
- ownership behavior;
- existing client usage;
- related integration tests;
- OpenAPI behavior when relevant.

Do not infer the contract from memory.

### 2. Define the contract explicitly

For each changed endpoint identify:

- HTTP method;
- path;
- authentication requirement;
- path parameters;
- query parameters;
- request body;
- response body;
- success status code;
- error status codes;
- validation behavior;
- ownership behavior.

Keep the contract minimal and intentional.

### 3. Preserve backward compatibility

Before changing an existing contract, determine whether current clients depend on it.

Prefer additive changes over breaking changes.

Avoid changing:

- field names;
- field meaning;
- response shape;
- status codes;
- required/optional behavior

unless the task explicitly requires it.

If a breaking change is necessary, make it explicit.

### 4. Keep ownership server-controlled

Never require clients to send `user_id` or equivalent ownership identifiers when identity is derived from authentication.

Use the authenticated user context on the server.

Do not trust client-supplied ownership data.

### 5. Validate at the correct boundary

Use request schemas for:

- required fields;
- types;
- formats;
- structural validation.

Use service/business logic for:

- domain rules;
- ownership;
- state transitions;
- cross-field business constraints.

Use database constraints for invariants that must remain correct under concurrency.

### 6. Design errors consistently

Use existing project conventions for errors.

For each failure case define:

- status code;
- error type;
- message shape;
- whether the resource should appear as not found vs forbidden;
- validation response behavior.

Do not leak sensitive internal details.

Do not invent a second error format for one endpoint.

### 7. Keep PATCH semantics correct

For partial updates:

- distinguish omitted fields from explicitly provided null values;
- update only fields present in the request;
- preserve unchanged values;
- validate resulting business state.

Do not accidentally reset omitted fields.

### 8. Keep DELETE semantics clear

For deletion:

- define ownership behavior;
- define not-found behavior;
- define successful status code;
- define whether deletion is hard or soft;
- preserve related data according to product rules.

Destructive API behavior should be explicit.

### 9. Align clients with backend

When a contract changes, inspect affected clients.

Verify:

- request types;
- response types;
- mutation payloads;
- route parameters;
- error handling;
- cache invalidation where relevant.

Do not duplicate backend-only fields in client models without need.

### 10. Verify API behavior

Add or update integration tests for relevant cases:

- success;
- validation failure;
- unauthenticated access;
- ownership/cross-user access;
- not found;
- business-rule failure;
- partial update behavior;
- destructive action behavior.

Prefer endpoint-level tests for contract verification.

### 11. Check OpenAPI consistency

When relevant, verify that generated OpenAPI reflects:

- correct request schema;
- correct response schema;
- documented status codes;
- authentication requirements;
- field optionality.

Do not manually document behavior that contradicts actual schemas.

### 12. Final check

Before completion verify:

- backend and client agree;
- no unintended breaking change was introduced;
- ownership is server-controlled;
- validation behavior is explicit;
- errors are consistent;
- integration tests cover material behavior;
- no unrelated endpoint changes are included.

Report the contract change and the checks that were actually run.