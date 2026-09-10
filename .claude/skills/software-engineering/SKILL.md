# Software Engineering Skill

## Purpose

This skill defines the baseline software-engineering standards for Valor Finis.

It exists to ensure that code is:

- correct;
- readable;
- maintainable;
- testable;
- predictable;
- minimally coupled;
- strongly typed;
- safe to change;
- consistent with the existing architecture;
- free from unnecessary complexity.

This skill applies to implementation, refactoring, debugging, architecture work,
and code review.

This skill is a baseline.

More specialized skills such as security-engineering, database-engineering,
API-design, mobile-engineering, testing-strategy, and release-engineering
may add stricter requirements.

When two principles conflict, prefer the solution that minimizes overall
system complexity while preserving correctness, security, and business rules.

---

# 1. Core Decision Hierarchy

When making an engineering decision, use this priority order:

1. Correctness
2. Security and data integrity
3. Business requirements
4. Simplicity
5. Maintainability
6. Testability
7. Consistency with existing architecture
8. Performance based on evidence
9. Extensibility only when justified

Never sacrifice correctness or security for elegance.

Never sacrifice simplicity for speculative extensibility.

---

# 2. Inspect Before Edit

Before changing code:

- inspect the relevant files;
- inspect surrounding architecture;
- inspect existing tests;
- inspect current interfaces and contracts;
- inspect existing project patterns;
- inspect git diff/status when relevant;
- understand the current behavior before proposing a replacement.

Do not implement based on assumptions when the repository can answer the question.

Prefer reusing an established project pattern over introducing a new one.

---

# 3. KISS — Keep It Simple

## Rule

Use the simplest solution that correctly satisfies the current requirement.

Prefer:

- straightforward control flow;
- explicit code;
- small focused abstractions;
- standard language/framework features;
- boring, proven technology.

Avoid unnecessary:

- factories;
- managers;
- registries;
- generic frameworks;
- inheritance hierarchies;
- configuration layers;
- indirection;
- metaprogramming.

## Apply when

Always.

## Do not misuse

Simple does not mean:

- duplicated business rules;
- missing validation;
- ignoring edge cases;
- skipping proper architecture;
- putting everything into one function.

## Review question

Could this implementation be meaningfully simpler without losing correctness,
security, or maintainability?

---

# 4. YAGNI — You Aren't Gonna Need It

## Rule

Implement what the current requirement needs.

Do not build functionality for hypothetical future requirements.

Avoid:

- speculative extension points;
- unused configuration;
- generic plugin systems before multiple implementations exist;
- abstractions for features that do not exist;
- future-proofing without a concrete requirement.

## Good example

One OCR abstraction exists because multiple OCR implementations are realistically
replaceable infrastructure.

## Bad example

Building a dynamic OCR marketplace and runtime plugin registry when the product
currently supports only one configured OCR provider.

## Review question

Which current requirement requires this code?

If there is no concrete answer, reconsider whether the code should exist.

---

# 5. DRY — Don't Repeat Yourself

## Rule

Avoid duplicating knowledge, business rules, contracts, or authoritative logic.

DRY is primarily about duplicated knowledge, not visually similar code.

Do not automatically extract an abstraction because two blocks look similar.

Prefer the Rule of Three:

- first occurrence: implement clearly;
- second occurrence: observe similarity;
- third meaningful repetition: strongly consider abstraction.

## Examples of knowledge that should normally have one source of truth

- business rules;
- status definitions;
- API contracts;
- query-key conventions;
- validation rules;
- configuration defaults;
- ownership logic.

## Do not misuse

Premature DRY often creates:

- generic helpers;
- poorly named abstractions;
- hidden coupling;
- complicated parameter combinations.

## Review question

Are we removing real duplicated knowledge, or only making similar-looking code
share an abstraction?

---

# 6. SOLID

SOLID principles are engineering heuristics, not laws.

Apply them when they reduce coupling and improve clarity.

Do not introduce abstractions merely to claim SOLID compliance.

---

## 6.1 Single Responsibility Principle

A module should have one primary reason to change.

Examples:

- Router: HTTP concerns.
- Service: business logic.
- Repository: persistence operations.
- Schema: external/internal data contract.
- Provider: integration with external infrastructure.

Avoid modules that combine unrelated responsibilities.

### Review question

Can the responsibility of this module be described clearly in one sentence?

---

## 6.2 Open/Closed Principle

Prefer designs where expected variation can be introduced without rewriting
stable business logic.

Use abstractions when a real substitution boundary exists.

Example:

ReceiptOcrProvider

with implementations such as:

TesseractReceiptOcrProvider

or a future cloud OCR provider.

Do not create extension points for purely hypothetical variations.

---

## 6.3 Liskov Substitution Principle

Implementations of the same abstraction must honor the same behavioral contract.

A replacement implementation must not:

- return incompatible values;
- change ownership semantics;
- silently change failure behavior;
- introduce unexpected side effects.

---

## 6.4 Interface Segregation Principle

Prefer small interfaces focused on one capability.

Avoid broad interfaces that force implementations to support unrelated behavior.

---

## 6.5 Dependency Inversion Principle

Business logic should depend on stable abstractions rather than concrete
infrastructure where substitution provides real value.

Example:

ReceiptService
→ ReceiptOcrProvider
→ TesseractReceiptOcrProvider

Avoid embedding third-party infrastructure directly into core business logic.

---

# 7. Separation of Concerns

Keep unrelated concerns separate.

For backend code, preserve boundaries similar to:

Router
→ Service
→ Repository
→ Database

Infrastructure integrations should normally sit behind provider/adapter
boundaries.

For mobile code:

UI
→ feature/service layer
→ centralized API client
→ backend API

Do not mix:

- SQL with HTTP handling;
- UI rendering with persistence logic;
- business rules with framework-specific details;
- authentication logic with unrelated features.

---

# 8. High Cohesion

Code that changes for the same reason should normally live together.

Keep feature-specific logic close to its feature.

Example:

receipts/
- receipt_service
- receipt_repository
- receipt_schemas
- receipt_errors
- receipt_ocr_service

Avoid dumping unrelated functionality into generic utility modules.

---

# 9. Low Coupling

Modules should know as little as necessary about other modules.

Prefer narrow explicit interfaces.

Avoid:

- reaching through several internal objects;
- accessing another feature's internal implementation;
- circular dependencies;
- global mutable state;
- feature code depending on unrelated infrastructure details.

---

# 10. Composition Over Inheritance

Prefer composing behavior from focused components rather than creating deep
inheritance trees.

Prefer:

ReceiptService uses ReceiptOcrProvider

over:

BaseService
→ FinancialService
→ ReceiptService
→ GermanReceiptService
→ TesseractReceiptService

Inheritance is acceptable when there is a genuine substitutable "is-a"
relationship and the hierarchy remains simple.

---

# 11. Explicit Over Implicit

Important behavior should be visible from the code.

Prefer:

- explicit parameters;
- explicit return values;
- explicit state transitions;
- explicit dependencies;
- explicit errors.

Avoid excessive behavior hidden behind:

- globals;
- decorators;
- implicit mutation;
- magic callbacks;
- framework side effects;
- undocumented environment assumptions.

---

# 12. Principle of Least Surprise

Code should behave according to its name and contract.

A function named:

get_expense()

should not unexpectedly:

- modify budgets;
- delete records;
- emit unrelated external requests;
- mutate global state.

Unexpected side effects are a design smell.

---

# 13. Single Source of Truth

A business rule or system contract should have one authoritative definition.

Avoid multiple independent definitions of:

- status values;
- validation constraints;
- route paths;
- query-key conventions;
- configuration rules;
- ownership rules.

Do not create a second source of truth merely for convenience.

---

# 14. Pure Functions Where Practical

Prefer pure functions for:

- transformations;
- calculations;
- validation;
- parsing;
- mapping;
- formatting.

Pure functions:

- receive inputs;
- return outputs;
- avoid hidden state;
- avoid I/O;
- avoid global mutation.

Separate pure computation from external effects where practical.

A useful design model is:

Functional Core
+
Imperative Shell

The core contains deterministic logic.

The shell handles:

- network;
- filesystem;
- database;
- external services;
- UI side effects.

---

# 15. Immutability by Default

Avoid unnecessary mutation.

Prefer constructing new values when it improves predictability.

Mutation is acceptable when:

- it is localized;
- ownership is clear;
- the framework expects it;
- it simplifies the implementation.

Avoid shared mutable state.

---

# 16. Command–Query Separation

A function should normally either:

- return information;
- change state.

Avoid combining unrelated reads and writes under misleading names.

Examples:

get_expense()
update_expense()

are preferable to:

get_and_update_expense_state()

unless the combined operation is a real domain operation.

---

# 17. Design by Contract

Important functions and APIs should have explicit contracts.

A contract should make clear:

- accepted input;
- preconditions;
- output;
- postconditions;
- possible failures.

Example:

confirm_receipt

Precondition:
- receipt belongs to authenticated user;
- receipt status is processed.

Postcondition:
- exactly one expense exists for the confirmation;
- receipt is confirmed;
- receipt references the created expense.

---

# 18. Make Invalid States Hard to Represent

Prefer types and structures that prevent contradictory state.

Bad:

type State = {
  loading: boolean;
  success: boolean;
  error: boolean;
};

This allows:

loading = true
success = true
error = true

Prefer:

type State =
  | { status: "loading" }
  | { status: "success"; data: Data }
  | { status: "error"; error: Error };

Use enums, unions, validated schemas, domain types, and database constraints
where they materially reduce invalid state.

---

# 19. Strong Typing

Use the most accurate practical type.

TypeScript:

- strict mode;
- no `any`;
- use discriminated unions where appropriate;
- avoid unsafe casts;
- define API contracts explicitly.

Python:

- type hints;
- Pydantic schemas;
- UUID for identifiers;
- Decimal for money;
- date/datetime for dates;
- Optional only when a value is truly optional.

Avoid generic `dict`, `object`, `str`, or `float` when a meaningful domain type
exists.

---

# 20. Parse, Don't Validate

Convert external raw input into trusted typed data at system boundaries.

Preferred flow:

HTTP / environment / external response
→ validation/parsing
→ typed domain/application data
→ business logic

Do not repeatedly pass unvalidated primitive values deep into the application.

---

# 21. Guard Clauses and Early Returns

Prefer linear control flow.

Bad:

if receipt:
    if receipt.status:
        if receipt.status == "processed":
            ...

Prefer:

if receipt is None:
    raise ReceiptNotFoundError()

if receipt.status != "processed":
    raise ReceiptConfirmationNotAllowedError()

...

Avoid unnecessary nesting.

---

# 22. One Level of Abstraction

A function should preferably operate at one conceptual level.

Do not mix orchestration with low-level implementation details unnecessarily.

Example:

process_receipt()

may coordinate:

- load receipt;
- OCR;
- parse;
- save result.

Low-level SQL, subprocess construction, HTTP parsing, and filesystem manipulation
should normally live in their dedicated layers.

---

# 23. Function Design

Functions should do one coherent thing.

There is no universal maximum function length.

Do not enforce arbitrary limits such as "20 lines".

Use these signals instead:

- too many responsibilities;
- too many branches;
- deep nesting;
- mixed abstraction levels;
- difficult naming;
- difficult testing;
- high cognitive complexity.

Extract functions when the extraction creates a meaningful concept.

Do not create meaningless functions such as:

handle()
execute()
process()
perform()
doStuff()

only to reduce line count.

---

# 24. Naming

Names should communicate intent.

Prefer:

get_expense_by_id
confirm_receipt
calculate_budget_remaining
validate_receipt_expense_link

Avoid vague names:

data
thing
manager
helper
processData
handleStuff
temp
x

Boolean names should normally communicate a predicate:

is_visible
has_access
can_delete
should_retry

Use domain language consistently.

---

# 25. Avoid Magic Values

Give domain-significant values meaningful names or configuration.

Bad:

if attempts > 7:

Better:

if attempts > MAX_OCR_RETRY_COUNT:

Do not create constants for values that have no independent meaning.

---

# 26. Avoid Ambiguous Boolean Parameters

Avoid calls such as:

process_receipt(receipt, True, False)

Prefer named arguments:

process_receipt(
    receipt=receipt,
    retry_failed=True,
)

For more complex modes, prefer enums or separate operations.

---

# 27. Avoid Global Mutable State

Avoid state shared implicitly across unrelated code.

Global mutable state causes:

- hidden dependencies;
- race conditions;
- test pollution;
- unpredictable behavior.

Prefer explicit dependency ownership and lifecycle management.

---

# 28. Dependency Injection

Use dependency injection when it improves:

- testability;
- replaceability;
- boundary clarity.

Production:

ReceiptOcrProvider
→ TesseractReceiptOcrProvider

Tests:

ReceiptOcrProvider
→ FakeReceiptOcrProvider

Do not introduce dependency-injection frameworks unless they provide clear value.

---

# 29. Fail Fast

Invalid configuration or impossible state should fail as early as practical.

Do not silently use unsafe or unexpected fallbacks.

Example:

Unsupported RECEIPT_OCR_DRIVER
→ application startup failure

not:

Unsupported driver
→ silently use another provider

---

# 30. Defensive Programming

External systems and users are unreliable.

Account for:

- invalid input;
- failed network requests;
- duplicate requests;
- timeouts;
- corrupt files;
- unavailable external providers;
- partially completed operations;
- application interruption.

Use appropriate:

- validation;
- bounds;
- timeouts;
- transactions;
- idempotency;
- retries only where safe.

Do not over-defend internal code against states already made impossible by a
trusted validated boundary.

---

# 31. Error Handling

Never silently swallow errors.

Avoid:

try:
    ...
except:
    pass

Avoid broad exception handling unless required for:

- rollback;
- cleanup;
- translation to a domain error;
- logging followed by re-raise.

Prefer:

Infrastructure/library error
→ application/domain error
→ HTTP/UI mapping

Do not expose:

- stack traces;
- filesystem paths;
- SQL details;
- secrets;
- provider credentials.

Errors should be predictable and actionable.

---

# 32. Exceptions Are Not Normal Control Flow

Do not use exceptions for ordinary expected branching when a clear conditional
or result type is more appropriate.

Use exceptions for exceptional failure states.

---

# 33. Atomicity

A business operation that must remain consistent should be atomic.

Example:

Create Expense
+
Mark Receipt confirmed

should either:

- both succeed;
- both roll back.

Do not allow partial business state.

---

# 34. Idempotency

Operations that may be retried must be protected against duplicate effects.

Especially important for:

- financial operations;
- receipt confirmation;
- webhooks;
- external callbacks;
- background jobs;
- retrying network clients.

UI single-flight protection is useful but is not a substitute for backend/data
integrity guarantees.

---

# 35. Concurrency Safety

Assume operations may happen concurrently.

Consider:

- two devices;
- retries;
- duplicate requests;
- workers;
- race conditions.

Use appropriate protection:

- transactions;
- database constraints;
- locking;
- idempotency keys;
- compare-and-set/state-transition rules.

Do not rely solely on frontend button disabling.

---

# 36. Data Integrity

Use database-level constraints where they protect important invariants.

Application validation and database constraints should complement each other.

Examples:

- foreign keys;
- unique constraints;
- check constraints;
- non-null constraints.

Do not trust application checks alone for critical integrity rules when the
database can enforce the invariant.

---

# 37. Money Handling

Never use binary floating-point for persisted financial values.

Use:

- Decimal in Python;
- Numeric/Decimal in database;
- validated decimal strings or equivalent precise representations across APIs.

Define rounding explicitly where rounding is part of the business rule.

---

# 38. Date and Time Handling

Use explicit date/time types.

Distinguish:

- calendar date;
- local datetime;
- UTC timestamp.

Avoid parsing or comparing dates as arbitrary strings except at serialization
boundaries.

Be explicit about timezone assumptions.

---

# 39. Validate at Trust Boundaries

Validate external data at boundaries such as:

- HTTP requests;
- file uploads;
- environment configuration;
- third-party responses;
- external events.

After parsing into trusted domain/application types, avoid redundant validation
at every internal function unless a different invariant applies.

---

# 40. Input Bounds

User-controlled or external input should normally have reasonable bounds.

Examples:

- string lengths;
- file size;
- decoded image dimensions;
- array length;
- pagination size;
- request size;
- execution time.

Unbounded input is a correctness, reliability, and security risk.

---

# 41. Safe Resource Management

Resources must have clear lifecycles.

Examples:

- files;
- temporary files;
- database sessions;
- transactions;
- network streams;
- subscriptions.

Prefer language/framework lifecycle primitives such as context managers,
RAII-like abstractions, cleanup callbacks, and finally blocks.

---

# 42. Law of Demeter

Avoid unnecessary knowledge of another object's internal structure.

Long chains such as:

order.user.profile.account.settings.currency.code

are often a sign of excessive coupling.

Expose meaningful operations or narrower data when practical.

---

# 43. Performance

Correctness comes before optimization.

Do not optimize based on assumptions.

Preferred process:

measure
→ identify bottleneck
→ optimize
→ measure again

Avoid sacrificing readability for insignificant performance gains.

---

# 44. Prefer Proven Technology

Prefer stable, actively maintained, well-documented technologies over novelty
unless the newer technology solves a concrete project problem.

Minimize dependencies.

Every dependency adds:

- maintenance cost;
- upgrade cost;
- security surface;
- compatibility risk.

Before adding a dependency, ask:

1. Is it actually required?
2. Does the platform/framework already provide this capability?
3. Is it actively maintained?
4. Can the task be solved simply without it?

---

# 45. Refactoring

Refactoring changes internal structure without intentionally changing external
behavior.

Refactor in small verified steps.

Keep tests green.

Do not combine large unrelated refactors with feature work.

The Boy Scout Rule does not authorize uncontrolled scope expansion.

Improve nearby code only when:

- the improvement is directly relevant;
- risk is low;
- the diff remains understandable.

Otherwise create a separate task.

---

# 46. Minimal Diff Principle

Make the smallest coherent change that solves the task correctly.

Do not perform unrelated cleanup.

Do not change architecture without necessity.

Do not reformat unrelated files.

Do not rename unrelated code.

Do not introduce dependencies unrelated to the requirement.

Small diffs are easier to:

- review;
- test;
- understand;
- revert;
- debug.

---

# 47. TDD

Use Test-Driven Development where it provides strong value.

Preferred cycle:

RED
→ GREEN
→ REFACTOR

TDD is especially valuable for:

- business logic;
- validation;
- parsers;
- financial calculations;
- state transitions;
- authorization;
- concurrency-sensitive rules.

Do not use TDD dogmatically for trivial declarative UI or configuration where
test-first provides little value.

---

# 48. Test Behavior, Not Implementation

Tests should verify observable contracts and business behavior.

Prefer:

"confirming a processed receipt creates exactly one linked expense"

over:

"private method X was called exactly two times"

Implementation-detail tests create fragile suites and discourage refactoring.

Mocks should represent real architectural boundaries.

Do not mock every internal function.

---

# 49. Testing Strategy

Use the right test at the right level.

Unit tests:
- pure logic;
- validators;
- parsers;
- calculations.

Integration tests:
- API;
- database;
- repositories;
- framework wiring;
- feature boundaries.

Contract tests:
- external/internal API schemas and assumptions.

E2E:
- critical business journeys.

Prefer a risk-based testing portfolio over arbitrary coverage percentages.

---

# 50. Negative Testing

Test failure behavior, not only happy paths.

Consider:

- invalid input;
- missing input;
- malformed data;
- boundary values;
- foreign-owned resources;
- duplicate operations;
- corrupt files;
- provider failures;
- timeouts;
- unavailable dependencies.

---

# 51. Property-Based Testing

Use property-based testing when a component accepts broad input spaces.

Useful for:

- money;
- dates;
- parsers;
- serialization;
- validation;
- transformations.

Typical tools:

Python:
- Hypothesis

TypeScript:
- fast-check

Use when generated inputs can reveal edge cases that example-based tests may miss.

---

# 52. Mutation Testing

Use mutation testing selectively for critical logic.

Good targets:

- financial calculations;
- authorization;
- important state transitions;
- critical validation.

Mutation testing verifies whether the tests actually detect behavioral changes.

It does not need to run on every file or every commit.

---

# 53. Static Analysis

Use static tools to detect errors before runtime.

Examples:

TypeScript:
- TypeScript compiler;
- ESLint.

Python:
- type checking where configured;
- linting/static analysis.

Security-specific static analysis belongs to the security-engineering skill.

Do not suppress static-analysis findings without a documented reason.

---

# 54. Automated Formatting

Formatting should be automated.

Do not spend code-review effort debating whitespace or trivial formatting.

Use the project's configured formatter and style rules.

Do not introduce a different formatter without explicit agreement.

---

# 55. Comments

Comments should primarily explain WHY.

Avoid comments that merely repeat the code.

Bad:

# Increment counter
counter += 1

Useful:

# Prevent retrying this provider indefinitely after a permanent failure.

Use comments for:

- non-obvious constraints;
- compatibility workarounds;
- architectural reasoning;
- intentional tradeoffs.

Remove obsolete comments when behavior changes.

---

# 56. Docstrings and Public Documentation

Public/non-obvious functions should be documented when documentation adds value.

Valor Finis Python docstrings should use:

What:
    What the function/component does.

Why:
    Why this function/component exists.

Parameters:
    Inputs and their purpose.

Returns:
    Result and meaning.

Raises:
    Expected domain/application failures.

Do not write verbose docstrings that merely restate obvious code.

---

# 57. API Contracts

API contracts must be explicit and stable.

Use:

- Pydantic schemas;
- OpenAPI;
- TypeScript types;
- typed request/response models.

Do not expose ORM/database models directly as public contracts unless explicitly
designed that way.

Avoid undocumented response-shape changes.

---

# 58. Backward Compatibility

Do not break existing consumers unnecessarily.

When changing a public contract:

- identify consumers;
- evaluate migration path;
- prefer additive changes where practical;
- document intentional breaking changes.

Do not preserve harmful legacy behavior indefinitely merely for compatibility.

---

# 59. Database Changes

Schema changes must use the project's migration system.

For Valor Finis:

Alembic is the authoritative migration mechanism.

Do not modify production schema manually as a substitute for a migration.

Migrations should:

- be deterministic;
- preserve existing data;
- have safe constraints;
- be tested against realistic state;
- account for deployment ordering.

Prefer expand-and-contract migration patterns when backward compatibility across
deployments matters.

---

# 60. Observability-Friendly Code

Important operations should be diagnosable in production.

Use meaningful:

- structured logs;
- request identifiers;
- domain events;
- metrics where useful.

Do not log secrets or sensitive content without an explicit requirement.

Observability should help answer:

- what failed?
- where?
- for which operation?
- how often?
- how long did it take?

Detailed security logging rules belong to the security-engineering skill.

---

# 61. Code Review Standard

A reviewer should evaluate:

1. Correctness
2. Business-rule compliance
3. Architecture
4. Data integrity
5. Error handling
6. Edge cases
7. Concurrency where relevant
8. Tests
9. Readability
10. Maintainability
11. Dependency changes
12. Scope discipline

Formatting alone is not code review.

Review the actual diff and relevant surrounding code.

Do not trust implementation claims without evidence.

---

# 62. Evidence Over Claims

Statements such as:

- "tests pass";
- "this API exists";
- "the dependency is compatible";
- "no backend files changed";

must be verified when verification is available.

Prefer evidence such as:

- command output;
- tests;
- static checks;
- repository inspection;
- actual diff;
- documented API contract;
- CI result.

Agent confidence is not evidence.

---

# 63. Definition of Done

Code is not done because implementation exists.

A task is engineering-complete only when applicable requirements are satisfied:

- requested behavior implemented;
- architecture respected;
- types/static checks pass;
- relevant tests pass;
- error paths handled;
- important edge cases covered;
- no unnecessary dependency added;
- no unrelated diff;
- no dead temporary code;
- documentation updated when required;
- migration included when required;
- required review completed.

Security and release requirements are defined by their dedicated skills and may
add additional mandatory gates.

---

# 64. Principle Conflict Resolution

Engineering principles can conflict.

Examples:

DRY vs KISS
Open/Closed vs YAGNI
Abstraction vs readability
Performance vs simplicity

When principles conflict, choose the design that:

1. preserves correctness;
2. preserves security and data integrity;
3. satisfies the current requirement;
4. has the lowest justified complexity;
5. is easiest to understand and verify;
6. remains consistent with the project architecture.

Do not mechanically optimize for one named principle.

---

# 65. Mandatory Review Questions

Before declaring implementation complete, ask:

- Is the behavior correct?
- Is this the simplest correct implementation?
- Did we add anything not required by the task?
- Did we duplicate business knowledge?
- Are responsibilities clearly separated?
- Are dependencies pointing in the correct direction?
- Are types precise?
- Are invalid states prevented where practical?
- Are failures handled predictably?
- Are important operations atomic/idempotent where necessary?
- Are concurrency risks addressed where relevant?
- Are tests checking behavior instead of internals?
- Is there an unnecessary dependency?
- Is there unrelated code in the diff?
- Can another engineer understand why this code exists?
- Is there evidence supporting the implementation claims?

If an answer reveals a material weakness, resolve it or explicitly report it.