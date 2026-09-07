---
name: mobile-feature
description: Implements mobile application features using the repository's existing Expo, React Native, Expo Router, TypeScript, API-client, authentication, and server-state patterns.
---

# Mobile Feature

Use this skill when implementing or modifying mobile application behavior.

## Goal

Deliver the smallest complete mobile feature while preserving existing navigation, authentication, API contracts, state-management boundaries, TypeScript safety, and user experience.

## Workflow

### 1. Inspect before editing

Read the relevant:

- route files;
- feature screens;
- feature types;
- feature services;
- API client;
- TanStack Query usage;
- authentication context;
- navigation patterns;
- validation helpers;
- related UI components;
- existing loading, empty, and error states.

Search for similar existing features before introducing a new pattern.

Do not guess the current mobile architecture.

### 2. Define the user flow

Before implementation, identify:

- how the user enters the feature;
- what data is required;
- what the user can change;
- success behavior;
- validation behavior;
- loading behavior;
- empty behavior;
- error behavior;
- cancellation/back-navigation behavior;
- what data must refresh after a mutation.

Implement the complete user flow, not only the happy-path UI.

### 3. Preserve architectural boundaries

Follow the existing flow:

Route
→ Feature screen/component
→ Feature service
→ Central API client
→ Backend API

Use TanStack Query for server state.

Use Auth Context only for authentication/session state.

Do not introduce duplicate API clients.

Do not perform direct backend requests from presentation components when an existing feature service or API layer should own them.

### 4. Preserve navigation structure

Use existing Expo Router conventions.

When adding or restructuring routes:

- inspect the current route tree first;
- preserve protected-route behavior;
- avoid duplicate route ownership;
- ensure back navigation remains predictable;
- verify dynamic route parameters;
- verify direct navigation to the route when relevant.

Do not restructure unrelated routes.

### 5. Maintain strict TypeScript

Use explicit domain types.

Do not use `any`.

Prefer shared feature types for API inputs and outputs.

Keep optional and nullable values intentional.

Do not hide type errors with unsafe casts unless there is a documented external-library limitation.

Run TypeScript verification after changes.

### 6. Handle server state correctly

Use TanStack Query for:

- fetching;
- caching;
- mutations;
- loading state;
- error state;
- invalidation/refetching.

After a successful mutation, invalidate or update every affected query family.

Do not rely on navigation alone to refresh stale data.

Avoid duplicating server data into local state unless temporary form state requires it.

### 7. Handle forms and validation

For create/edit flows:

- initialize form state intentionally;
- reuse shared validation when create and edit have the same rules;
- validate before mutation;
- preserve meaningful backend validation errors when appropriate;
- prevent accidental duplicate submissions;
- keep user input when a recoverable request fails.

Do not duplicate validation logic across screens without a reason.

### 8. Handle destructive actions safely

For delete or other destructive actions:

- require explicit user confirmation;
- make the action visually distinct;
- do not perform the mutation before confirmation;
- keep the user on the current screen if deletion fails;
- navigate only after confirmed success;
- invalidate affected server-state queries.

Use platform-native confirmation patterns when they fit the existing application.

### 9. Cover user-facing states

For relevant screens, intentionally handle:

Loading
→ Content
→ Empty
→ Error

For mutations also handle:

Idle
→ Pending
→ Success / Error

Do not leave the user without feedback during meaningful asynchronous actions.

### 10. Preserve API contracts

Do not invent client fields that the backend does not support.

Do not send ownership identifiers that are derived from authentication on the server.

Keep request and response types aligned with the backend contract.

If the API contract itself must change, use the `api-contract` skill.

### 11. Consider platform behavior

When relevant, verify:

- iOS behavior;
- Android behavior;
- keyboard interaction;
- scrolling;
- safe areas;
- touch targets;
- dialogs;
- navigation;
- date/time input;
- network failure behavior.

Do not add a new dependency when React Native, Expo, or an existing project dependency already provides the required behavior.

### 12. Verify progressively

Run the smallest relevant checks first.

Then run broader verification.

At minimum for meaningful mobile changes, verify when available:

- TypeScript;
- lint;
- relevant automated tests;
- route correctness;
- manual E2E flow on the supported development target.

Do not report manual E2E as completed unless it was actually performed.

If device/simulator verification is blocked, state exactly what remains unverified.

### 13. Final check

Before completion verify:

- the complete user flow works;
- loading/error/empty states are intentional;
- server state refreshes correctly;
- navigation behaves correctly;
- no `any` was introduced;
- no duplicate API or state-management pattern was introduced;
- no unrelated files were changed;
- TypeScript and lint are green;
- manual E2E requirements are identified.

Report exactly what was changed and which checks were actually run.