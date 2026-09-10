# Security Engineering Skill

## Purpose

This skill defines the baseline security-engineering standard for Valor Finis.

Security is not a final review step.

Security must be considered throughout the entire engineering lifecycle:

Security Design
→ Implementation
→ Verification
→ Release
→ Runtime Monitoring
→ Incident Response

This skill applies to:

- architecture;
- backend development;
- mobile development;
- APIs;
- authentication;
- authorization;
- databases;
- file uploads;
- external integrations;
- infrastructure;
- CI/CD;
- dependency management;
- logging;
- production configuration;
- code review.

This skill complements the `software-engineering` skill.

When security requirements conflict with convenience, prefer security unless
the tradeoff is explicitly understood, documented, and approved.

Never weaken a security boundary merely to make a feature easier to implement.

---

# 1. Security Decision Priority

Use this priority order for security decisions:

1. Prevent unauthorized access.
2. Preserve confidentiality.
3. Preserve data integrity.
4. Preserve authentication and authorization guarantees.
5. Prevent privilege escalation.
6. Prevent data leakage.
7. Prevent destructive abuse.
8. Preserve availability.
9. Preserve auditability.
10. Minimize attack surface.
11. Minimize operational complexity.

Security controls should be proportional to the actual risk.

Do not introduce unnecessary security complexity that creates additional bugs.

---

# 2. Security Is Part of Design

Before implementing a meaningful feature, identify:

- assets;
- actors;
- data being processed;
- trust boundaries;
- entry points;
- privileged operations;
- external dependencies;
- abuse scenarios;
- security invariants;
- failure behavior.

Do not wait until code review to discover the security model.

For high-risk features, produce a lightweight threat model before implementation.

---

# 3. Security Lifecycle

Every relevant task should go through four security stages.

## Stage 1 — Security Design

Before implementation:

- identify sensitive assets;
- identify trust boundaries;
- identify threats;
- define security invariants;
- define authorization rules;
- define validation requirements;
- define resource limits;
- define secrets/config requirements;
- identify external dependencies.

## Stage 2 — Secure Implementation

During implementation:

- preserve trust boundaries;
- enforce authorization server-side;
- validate untrusted input;
- use safe APIs;
- avoid insecure defaults;
- minimize privileges;
- avoid secret exposure;
- implement limits/timeouts;
- maintain transaction and concurrency safety.

## Stage 3 — Security Verification

Before release:

- review actual diff;
- run negative tests;
- test ownership boundaries;
- test malformed input;
- inspect dependencies;
- inspect secret exposure;
- inspect logging;
- inspect concurrency-sensitive operations;
- inspect configuration defaults.

## Stage 4 — Runtime Security

After deployment:

- monitor failures and suspicious patterns;
- detect unusual authentication activity;
- detect abuse/resource exhaustion;
- monitor dependency vulnerabilities;
- maintain incident-response capability;
- rotate compromised credentials;
- preserve audit evidence without leaking sensitive data.

---

# 4. Security Invariants

Security invariants are rules that must remain true regardless of feature.

Agents must identify which invariants a change can affect.

Project-wide examples for Valor Finis include:

SEC-001:
A user must never read another user's private financial resources.

SEC-002:
A user must never modify or delete another user's resources.

SEC-003:
Client-provided `user_id` must never determine resource ownership.

SEC-004:
Authenticated user identity must come from a verified authentication context.

SEC-005:
Privileged backend credentials must never be shipped in a mobile or web client.

SEC-006:
Secrets must never be committed to source control.

SEC-007:
Secrets must never appear in normal logs or user-visible error messages.

SEC-008:
Uploaded files must be treated as untrusted data.

SEC-009:
User-controlled filenames must never directly determine server filesystem paths.

SEC-010:
Financial operations must preserve integrity under retries and concurrency.

SEC-011:
Security-sensitive configuration must fail closed.

SEC-012:
Authorization must be enforced for every protected operation, not only during
initial resource retrieval.

SEC-013:
External provider failures must not expose credentials, filesystem paths,
stack traces, or internal infrastructure details.

SEC-014:
Sensitive data must not become publicly accessible by default.

SEC-015:
A failed operation must not leave security-sensitive partial state.

When a new permanent invariant is discovered, document it rather than keeping
it only inside a task description.

---

# 5. Threat Modeling

Use threat modeling before high-risk or trust-boundary changes.

Consider at minimum:

- who can interact with the feature;
- what they control;
- what data they can manipulate;
- what resources are protected;
- what external systems are involved;
- what happens if the user is malicious rather than accidental.

A lightweight STRIDE analysis may be used.

## Spoofing

Can an attacker impersonate another user or service?

Consider:

- forged tokens;
- stolen tokens;
- weak session validation;
- incorrect identity mapping.

## Tampering

Can an attacker modify:

- requests;
- IDs;
- files;
- stored data;
- external callbacks;
- state transitions?

## Repudiation

Can important operations occur without sufficient auditability?

## Information Disclosure

Can the system reveal:

- personal data;
- financial data;
- secrets;
- internal IDs where inappropriate;
- filesystem paths;
- SQL;
- stack traces;
- infrastructure topology?

## Denial of Service

Can inputs cause excessive:

- CPU;
- memory;
- storage;
- database work;
- external API usage;
- subprocess runtime?

## Elevation of Privilege

Can a user gain:

- another user's access;
- administrator behavior;
- backend privileges;
- storage permissions;
- privileged API access?

Threat modeling should produce concrete controls, not only a list of threats.

---

# 6. Trust Boundaries

Treat data crossing a trust boundary as untrusted until verified.

Common trust boundaries:

Mobile client
→ Backend API

Browser
→ Backend API

Backend
→ Database

Backend
→ Object storage

Backend
→ OCR provider

Backend
→ third-party API

Environment variables
→ application configuration

Uploaded file
→ parser/decoder

Webhook
→ backend

Do not assume a trusted mobile application.

Mobile and browser clients can be:

- modified;
- reverse engineered;
- scripted;
- replayed;
- fully controlled by an attacker.

---

# 7. Data Classification

Classify data according to sensitivity.

A practical project classification:

## PUBLIC

Safe for public disclosure.

Examples:

- marketing content;
- public documentation.

## INTERNAL

Not secret but not intentionally public.

Examples:

- architecture details;
- internal identifiers;
- operational metadata.

## PERSONAL

User-related information.

Examples:

- email address;
- account metadata;
- merchant history.

## SENSITIVE

Information requiring stronger protection.

Examples:

- expenses;
- financial history;
- receipt images;
- purchase history.

## SECRET

Credentials or material that grants privileged access.

Examples:

- database password;
- private API keys;
- service-role credentials;
- signing secrets;
- provider credentials.

Security controls must become stricter as sensitivity increases.

---

# 8. Authentication

Authentication answers:

"Who is making this request?"

Authentication must be verified server-side.

Never trust:

- user ID from request body;
- user ID from query parameters;
- hidden mobile fields;
- client-side authentication state alone.

Authentication tokens must be:

- validated;
- correctly scoped;
- checked for expiration where applicable;
- handled through approved libraries/framework mechanisms.

Do not implement custom cryptographic token verification when a proven
framework implementation exists.

---

# 9. Authorization

Authorization answers:

"What may this authenticated identity do?"

Authentication does not imply authorization.

Every protected operation must verify authorization.

Examples:

GET resource
PATCH resource
DELETE resource
CONFIRM resource
UPLOAD attachment
DOWNLOAD attachment

All require independent authorization enforcement where applicable.

Do not rely on:

- frontend visibility;
- disabled buttons;
- route guards;
- client-side checks.

Authorization must ultimately be enforced at the backend boundary.

---

# 10. Ownership Enforcement

For user-owned resources:

Backend identity
→ ownership-scoped query
→ resource

Prefer patterns similar to:

WHERE resource.id = requested_id
AND resource.user_id = current_user.id

Do not:

1. query arbitrary resource by ID;
2. return it;
3. trust that the caller used their own ID.

Ownership filtering should be difficult to accidentally omit.

Repository/service patterns should reinforce this invariant.

---

# 11. Principle of Complete Mediation

Every access to a protected resource must pass through an authorization decision.

Do not assume:

"Ownership was checked when the screen opened, therefore later operations are safe."

Each operation must preserve the boundary independently.

This includes:

- reads;
- mutations;
- exports;
- downloads;
- confirmations;
- background actions.

---

# 12. Least Privilege

Give each component the minimum permissions required.

Examples:

Mobile:
- public/publishable credentials only.

Backend:
- only required database/storage/provider privileges.

CI:
- only permissions required for the workflow.

Third-party provider:
- narrowly scoped credentials where possible.

Avoid broad administrative credentials for ordinary operations.

---

# 13. Secure Defaults

The default configuration must be the safer configuration.

Bad:

unknown AUTH_MODE
→ development authentication

Better:

unknown AUTH_MODE
→ startup failure

Bad:

missing authorization configuration
→ permit access

Better:

missing configuration
→ fail closed

Security-sensitive fallback behavior must be explicit.

---

# 14. Fail Closed

When a security decision cannot be made safely, deny or fail.

Examples:

invalid token
→ reject request

unknown storage driver
→ fail startup

unsupported security configuration
→ fail startup

Do not silently downgrade security.

---

# 15. Input Validation

All untrusted input must be validated at its trust boundary.

Validate relevant properties such as:

- type;
- format;
- length;
- range;
- enum membership;
- structure;
- required fields;
- relationships to authenticated resources.

Prefer allowlists over denylists where practical.

Use framework/schema validation when available.

For Valor Finis:

Pydantic should normally validate API request schemas before business logic.

---

# 16. Parse, Then Trust the Parsed Type

Do not pass raw untrusted primitives deep into business logic when a validated
domain type can be created at the boundary.

Preferred:

HTTP input
→ Pydantic
→ UUID / Decimal / date / enum
→ service logic

Do not repeatedly parse the same untrusted value throughout the application.

---

# 17. Input Bounds

Every attacker-controlled resource dimension should be bounded where practical.

Examples:

- string length;
- file size;
- image pixel count;
- array size;
- pagination size;
- request body size;
- number of uploaded files;
- OCR execution time;
- query complexity.

A compressed-size limit alone may not protect against memory exhaustion.

A request count limit alone may not protect against expensive individual
operations.

---

# 18. Injection Prevention

Never build executable commands or query languages through unsafe string
concatenation using user input.

Protect against:

- SQL injection;
- shell injection;
- command injection;
- template injection;
- LDAP injection where applicable;
- path injection;
- expression injection.

Use:

- parameterized SQL/ORM APIs;
- safe subprocess argument lists;
- framework-safe templating;
- allowlisted commands/options.

Never use `shell=True` with user-controlled input.

Avoid `eval`, `exec`, dynamic code execution, or equivalent behavior with
untrusted data.

---

# 19. SQL Safety

Prefer ORM or parameterized queries.

Never construct SQL by concatenating untrusted values.

Raw SQL is acceptable when:

- necessary;
- parameterized;
- reviewed;
- tested.

Authorization constraints must remain present in raw queries.

---

# 20. Filesystem Safety

Treat all user-provided file metadata as untrusted.

Never use a user-provided filename directly as a server path.

Prefer:

- generated storage identifiers;
- generated UUID filenames;
- server-controlled directories;
- normalized internal paths.

Prevent:

- `../` traversal;
- absolute-path injection;
- null-byte tricks;
- overwriting application files;
- arbitrary file reads.

Temporary files must have controlled lifecycle and cleanup.

---

# 21. File Upload Security

Uploaded files are untrusted.

Validate:

- maximum upload size;
- supported content types;
- extension where relevant;
- decoded structure where appropriate;
- server-side ownership;
- storage location.

Do not rely solely on:

- client MIME type;
- filename extension;
- frontend validation.

When files are parsed or decoded, also consider:

- decompression bombs;
- parser vulnerabilities;
- excessive dimensions;
- excessive processing time;
- malicious metadata;
- malformed files.

Uploaded content should never become executable merely because of its filename.

---

# 22. File Processing Isolation

File-processing libraries increase attack surface.

For OCR/image/document processing:

- limit file size;
- limit decoded resource usage;
- enforce processing timeout;
- sanitize or normalize where appropriate;
- use server-controlled paths;
- avoid shell invocation;
- translate provider errors into controlled domain errors.

Consider stronger isolation when processing risk grows.

Do not expose parser/library stack traces to clients.

---

# 23. Path Traversal Prevention

User-controlled data must never be able to escape an intended filesystem root.

Avoid constructions equivalent to:

uploads / user_filename

unless strict safe normalization is guaranteed.

Prefer server-generated internal storage paths.

---

# 24. SSRF Prevention

Any feature that can cause the backend to fetch a user-controlled URL must be
treated as an SSRF risk.

Protect against access to:

- localhost;
- private network ranges;
- cloud metadata endpoints;
- internal admin services;
- unexpected protocols.

Prefer allowlisted hosts/providers when remote URL fetching is required.

Do not add generic URL-fetch functionality casually.

---

# 25. XSS Prevention

For web-facing applications:

Treat user-generated text as data, not HTML.

Prefer framework auto-escaping.

Avoid unsafe HTML rendering.

Do not use mechanisms equivalent to:

dangerouslySetInnerHTML

unless the content is explicitly sanitized and the requirement is justified.

Security must exist even if the initial client is mobile, because the same API
may later be consumed by web clients.

---

# 26. CSRF

For cookie-authenticated browser flows, evaluate CSRF protection.

Bearer-token APIs used from mobile clients have a different threat model.

Do not blindly add or remove CSRF controls without understanding the
authentication mechanism.

---

# 27. CORS

CORS is not an authorization mechanism.

Configure only required origins, methods, and headers.

Do not assume that denying a browser origin prevents direct API requests.

Never replace backend authorization with CORS policy.

---

# 28. Secrets Management

Secrets must never be committed to source control.

Secrets include:

- API keys;
- private credentials;
- database URLs containing passwords;
- service-role keys;
- signing secrets;
- private tokens.

Use:

- environment variables;
- approved secret stores;
- CI secret mechanisms.

Do not hard-code secrets.

---

# 29. Secret Handling by Agents

Agents must not unnecessarily display secrets.

Avoid commands such as:

cat .env

when only one non-secret configuration value is required.

Never copy complete secret-bearing environment files into:

- prompts;
- logs;
- commit messages;
- PR descriptions;
- test snapshots.

If a secret is accidentally exposed, treat it as compromised and recommend
rotation.

Do not claim a secret has been removed from history unless that has actually
been verified.

---

# 30. Client Credential Safety

Anything shipped in:

- mobile bundle;
- browser JavaScript;
- public static assets

must be considered recoverable by an attacker.

Never place privileged backend secrets in a client.

Client-side environment variables are not a secure secret store.

---

# 31. Cryptography

Do not invent cryptography.

Use established platform/framework libraries.

Do not design custom:

- encryption algorithms;
- password hashing;
- signatures;
- token formats;
- random generators.

Use cryptographically secure randomness for security-sensitive tokens.

Credentials and passwords must use appropriate established password-hashing
mechanisms when handled directly.

---

# 32. Encryption in Transit

Sensitive communication must use secure transport.

Production APIs and external integrations should use TLS/HTTPS.

Do not disable certificate verification to solve development issues.

Never ship production code containing:

verify=False

or equivalent insecure transport bypass without explicit approved justification.

---

# 33. Sensitive Data at Rest

Evaluate whether sensitive data requires additional protection beyond the
platform/database default.

Consider:

- receipt images;
- financial records;
- exported data;
- backups.

Do not invent application-level encryption without a clear threat model and
proper key-management strategy.

---

# 34. Error Handling and Information Disclosure

Client-visible errors should expose enough information to act but not enough
to reveal internals.

Do not expose:

- stack traces;
- SQL queries;
- database hostnames;
- filesystem paths;
- secrets;
- cloud credentials;
- private provider responses;
- internal exception objects.

Use stable domain/application errors.

Detailed errors may be logged server-side when safe.

---

# 35. Logging Security

Logs are a security boundary.

Never log:

- passwords;
- authentication tokens;
- secret keys;
- full authorization headers;
- database credentials.

Avoid logging sensitive financial or receipt contents unless explicitly
required.

Prefer structured logs containing safe identifiers and event context.

Example:

event = receipt_ocr_failed
receipt_id = safe internal identifier
provider = tesseract
duration_ms = 1200

Avoid logging the full OCR text by default.

---

# 36. Log Injection

Treat logged user-controlled strings carefully.

Use structured logging rather than manually constructing log lines.

Do not allow untrusted newline/control characters to create misleading log
records where the logging framework does not safely encode them.

---

# 37. Auditability

Security-sensitive operations should be diagnosable where appropriate.

Examples:

- authentication failures;
- ownership denial;
- secret/configuration failures;
- destructive actions;
- suspicious repeated uploads;
- provider failures.

Audit data should not itself expose sensitive content.

---

# 38. Privacy by Design

Collect only data needed for the product.

Do not persist unnecessary sensitive information merely because it is available.

For each sensitive field consider:

- why is it required?
- how long is it needed?
- who can access it?
- where is it stored?
- is it included in logs?
- can it be deleted?

---

# 39. Data Minimization

Store the minimum data required for the feature.

Avoid copying the same sensitive payload across:

- database;
- logs;
- analytics;
- caches;
- external providers

without clear need.

---

# 40. External Providers

Third-party services create new trust boundaries.

Before adding a provider, evaluate:

- what data is sent;
- what credentials are required;
- provider permissions;
- timeout behavior;
- failure modes;
- privacy implications;
- rate/cost abuse;
- dependency availability.

Wrap provider-specific behavior behind an appropriate boundary.

Do not expose provider errors directly to clients.

---

# 41. External Requests

All external network calls should consider:

- connection timeout;
- read timeout;
- bounded retry policy;
- authentication;
- TLS validation;
- response validation;
- rate limits;
- failure translation.

Retries must only occur when safe.

Avoid retry storms.

---

# 42. Timeout Everything That Can Hang

Potentially blocking external/resource-heavy operations should have bounded
execution time where practical.

Examples:

- HTTP requests;
- OCR;
- subprocesses;
- third-party APIs;
- database operations where supported.

An attacker should not be able to consume a worker indefinitely with one
request.

---

# 43. Rate Limiting and Abuse Prevention

Evaluate abuse potential for expensive or sensitive endpoints.

Examples:

- login;
- password reset;
- file upload;
- OCR;
- report generation;
- external provider invocation.

Controls may include:

- rate limits;
- quotas;
- concurrency limits;
- size limits;
- authentication requirements.

Do not blindly rate-limit all endpoints identically.

Apply controls based on cost and abuse risk.

---

# 44. Denial-of-Service Resistance

Consider both request volume and per-request cost.

Potential resource dimensions:

- CPU;
- RAM;
- disk;
- database connections;
- DB query complexity;
- external API cost;
- network bandwidth;
- subprocess time.

A 10 MB request may decode into a much larger in-memory representation.

A tiny input may trigger expensive processing.

Bound the expensive dimension, not only the obvious one.

---

# 45. Dependency Security

Every dependency adds attack surface.

Before adding a dependency, ask:

1. Is it necessary?
2. Is there an official/framework-provided alternative?
3. Is it maintained?
4. Is it compatible with the current runtime?
5. Does it introduce excessive transitive dependencies?
6. Does it require new permissions?
7. Does it process untrusted input?

Prefer minimal dependencies.

Pin versions according to project policy.

Keep lockfiles committed.

---

# 46. Supply Chain Security

Protect the dependency/build pipeline.

Use where appropriate:

- dependency lockfiles;
- dependency vulnerability scanning;
- automated update tooling;
- trusted package registries;
- secret scanning;
- CI permission minimization;
- container scanning;
- provenance/SBOM for mature release pipelines.

Do not install packages from untrusted arbitrary sources.

Review unexpected lockfile changes.

---

# 47. Package Installation

When adding a package:

- use the framework-recommended install mechanism where applicable;
- verify compatibility;
- avoid manually forcing incompatible versions;
- document why the dependency is required.

For Expo, prefer:

npx expo install <package>

when SDK compatibility matters.

Do not add a dependency merely to avoid writing a trivial safe function.

---

# 48. Deserialization

Do not deserialize untrusted data using unsafe mechanisms.

Avoid:

- arbitrary object deserialization;
- pickle from untrusted sources;
- dynamic code-bearing formats.

Prefer safe structured formats:

- JSON;
- validated schemas.

---

# 49. Serialization

Only expose fields intended for the API consumer.

Do not accidentally serialize:

- password hashes;
- secrets;
- internal credentials;
- privileged metadata;
- private infrastructure fields.

Use explicit response schemas.

---

# 50. Database Security

Database access should use:

- least-privileged credentials where practical;
- parameterized queries/ORM;
- transactions;
- constraints;
- user-scoped access patterns;
- controlled migration processes.

Do not expose database credentials to clients.

Do not allow user input to choose arbitrary table/column names without strict
allowlisting.

---

# 51. Data Integrity

Security includes integrity, not only confidentiality.

Important invariants should be protected by multiple appropriate layers:

Application validation
+
transaction
+
database constraint

Examples:

- unique relationships;
- valid status transitions;
- ownership;
- positive amounts;
- foreign-key integrity.

---

# 52. Transaction Security

Security-sensitive multi-step operations should be atomic.

Example:

confirm receipt
→ create expense
→ link receipt
→ mark receipt confirmed

should not leave partial state.

Rollback failures safely.

Do not perform a commit halfway through a logically atomic security-sensitive
operation unless intentionally designed.

---

# 53. Idempotency and Replay Safety

Consider request replay.

A retry must not accidentally:

- create duplicate financial records;
- duplicate external actions;
- duplicate webhook effects;
- bypass state transitions.

Use:

- database constraints;
- idempotency keys where appropriate;
- state checks;
- atomic transactions.

Frontend `isPending` is not a security boundary.

---

# 54. Race Conditions

Check security-sensitive check-then-act patterns.

Potential vulnerability:

check ownership/state
→ another request changes state
→ perform action based on stale assumption

Consider:

- database locking;
- atomic updates;
- compare-and-set;
- unique constraints;
- transaction isolation.

Concurrency should be analyzed for high-value state transitions.

---

# 55. Mobile Application Security

Assume the mobile binary is controlled by the attacker.

Never rely on:

- hidden screens;
- obscured API endpoints;
- disabled buttons;
- local validation;
- bundled constants

for security.

Backend must enforce real security rules.

Do not place privileged secrets in Expo/React Native bundles.

Sensitive local storage should use platform-appropriate secure storage when
actual secret material must be persisted.

---

# 56. Web Application Security

For web clients, additionally consider:

- XSS;
- CSRF;
- secure cookies;
- SameSite behavior;
- CSP;
- clickjacking protection;
- CORS;
- browser storage risks.

Do not store long-lived sensitive tokens in insecure browser storage without
understanding the threat model.

---

# 57. API Security

API endpoints should explicitly define:

- authentication requirements;
- authorization requirements;
- request schema;
- response schema;
- error behavior;
- size limits where relevant;
- rate/resource behavior where relevant.

Do not expose unintended mass-assignment fields.

Example:

Client should not be allowed to set:

user_id
owner_id
is_admin
internal_status

unless explicitly part of a secure contract.

---

# 58. Mass Assignment

Never automatically map arbitrary client JSON onto persistence models.

Use explicit request schemas.

A client must not gain access to privileged fields simply by adding them to the
request body.

---

# 59. Broken Object-Level Authorization

Treat arbitrary resource IDs as attacker-controlled.

For:

/expenses/{id}
/receipts/{id}
/categories/{id}

verify the resource belongs to or is permitted for the authenticated user.

Never assume UUID unpredictability is authorization.

---

# 60. Enumeration Resistance

Do not treat unguessable IDs as the primary security control.

Authorization must remain correct even if every resource ID becomes known.

Response behavior may intentionally avoid revealing whether a foreign resource
exists.

---

# 61. Configuration Security

Configuration is part of security.

Security-sensitive environment values should be:

- validated;
- allowlisted where appropriate;
- fail-fast;
- explicitly documented.

Avoid insecure hidden defaults.

Production configuration should not depend on accidental developer defaults.

---

# 62. Development vs Production

Development conveniences must not silently activate in production.

Examples:

- dev auth;
- debug mode;
- permissive CORS;
- fake providers;
- test credentials.

Production must require an explicit secure configuration.

Fail closed where environment ambiguity creates risk.

---

# 63. Debug Features

Debug endpoints, verbose exceptions, test bypasses, and development authentication
must not be unintentionally available in production.

Any test-only bypass should be clearly scoped and impossible to activate
accidentally.

---

# 64. Security Testing

Security tests should target adversarial behavior, not only happy paths.

Relevant tests may include:

- missing token;
- invalid token;
- expired token;
- foreign-owned resource;
- privilege escalation attempts;
- unexpected fields;
- malformed input;
- oversized input;
- corrupt files;
- fake MIME types;
- duplicate requests;
- concurrent requests;
- provider timeout;
- path traversal strings;
- injection payloads.

Use tests proportionally to risk.

---

# 65. Ownership Tests

For every user-owned CRUD resource, strongly consider tests proving:

User A can access User A resource.

User B cannot:

- read;
- modify;
- delete;
- confirm;
- attach;
- download

User A's resource.

Ownership tests are mandatory for new protected-resource APIs unless an equivalent
existing test clearly covers the boundary.

---

# 66. Negative Security Tests

Do not only verify:

valid request
→ success

Also verify:

malicious/invalid request
→ controlled failure

A security test should prove that an invariant cannot be violated.

---

# 67. Security Regression Tests

When fixing a security defect:

1. reproduce the defect;
2. add a regression test when practical;
3. implement the fix;
4. verify the exploit path is blocked;
5. verify normal behavior still works.

Do not rely solely on manual reasoning.

---

# 68. Static Application Security Testing

Use automated static security analysis where supported.

Potential tools may include:

- Semgrep;
- language-specific security linters;
- GitHub CodeQL.

Automated tools supplement human review.

They do not replace architecture-level security analysis.

Do not suppress a security finding merely because it is inconvenient.

Investigate whether it is:

- real;
- false positive;
- accepted risk.

---

# 69. Secret Scanning

Repository and CI should scan for accidentally committed secrets.

Potential mechanisms include:

- GitHub secret scanning;
- gitleaks;
- equivalent approved tooling.

If a real credential entered version control, removing the line is not enough.

The credential should generally be considered compromised and rotated.

---

# 70. Dependency Vulnerability Scanning

Monitor dependencies for known vulnerabilities.

Possible mechanisms:

- Dependabot;
- npm audit as one signal;
- pip/dependency scanners;
- container scanners.

Do not blindly upgrade dependencies solely to silence a scanner.

Assess:

- exploitability;
- affected runtime path;
- compatibility;
- fix version.

Critical/high exploitable vulnerabilities require prompt action.

---

# 71. Security Review Before Release

Security review must inspect the actual diff.

Review at minimum:

- authentication;
- authorization;
- ownership;
- input validation;
- trust boundaries;
- injection;
- file handling;
- secrets;
- logging;
- dependencies;
- failure behavior;
- timeouts;
- resource limits;
- concurrency;
- data integrity.

Do not review only the task description.

---

# 72. Independent Review

Where available, implementation and security review should use separate
reasoning contexts.

The implementation agent should not be the only authority declaring its own
code secure.

Use an independent reviewer for meaningful security-sensitive changes.

---

# 73. Security Finding Severity

Classify findings consistently.

## BLOCKER

Release must not proceed.

Examples:

- authentication bypass;
- arbitrary cross-user data access;
- exposed production secret;
- remote code execution;
- destructive authorization failure.

## HIGH

Serious exploitable weakness requiring resolution before normal release.

Examples:

- major privilege escalation;
- broad sensitive-data leakage;
- practical injection vulnerability.

## MEDIUM

Meaningful security weakness requiring remediation or explicit risk acceptance.

Examples:

- missing resource bounds on expensive user-controlled processing;
- insufficient ownership protection on a limited path;
- significant security misconfiguration.

## LOW

Hardening opportunity with limited practical impact.

## NONE

No material finding.

Severity is based on actual impact and exploitability, not how easy the fix is.

---

# 74. Security Findings Are Not Automatically Deferred

A finding being labeled LOW or MEDIUM does not automatically mean it should be
deferred.

Project policy may require fixing it before release.

Consider:

- attack surface;
- sensitive data involved;
- cost of fixing now;
- cost after deployment;
- whether the feature is new and not yet released.

For new untrusted-input processing, inexpensive resource-exhaustion protection
should normally be implemented before first production release.

---

# 75. Known Risk Register

Accepted risks must be explicit.

Record:

- risk;
- severity;
- affected component;
- reason for acceptance;
- compensating controls;
- follow-up task.

Do not allow important security concerns to disappear inside chat history or
review comments.

---

# 76. Security Debt

Security debt should have tracked ownership.

Examples:

- exposed credential awaiting rotation;
- fail-open configuration;
- missing rate limiting;
- missing security scan;
- weak legacy authorization model.

Do not silently accumulate security debt.

---

# 77. Deployment Security

Before deployment consider:

- required environment variables;
- secrets;
- database migrations;
- service permissions;
- new system packages;
- new external providers;
- backward compatibility.

Do not manually modify production infrastructure without understanding
reproducibility.

Production configuration should be reproducible.

---

# 78. Database Migration Security

Schema migrations can affect security and data integrity.

Review:

- default values;
- nullability;
- ownership columns;
- unique constraints;
- foreign keys;
- data exposure;
- rollback/deployment ordering.

Never depend on production code using a schema that has not been migrated.

---

# 79. Container Security

For containerized services:

- use minimal base images;
- install only required OS packages;
- remove package-manager caches;
- pin runtime/dependency versions according to project policy;
- avoid unnecessary tools;
- avoid running privileged processes where unnecessary.

Scan production images as the release pipeline matures.

---

# 80. CI/CD Security

CI pipelines are privileged systems.

Apply least privilege.

Protect:

- repository write permissions;
- secrets;
- deployment credentials;
- artifact integrity.

Untrusted PR code should not automatically receive production secrets.

Avoid overly broad workflow permissions.

---

# 81. Release Security Gates

A security-sensitive feature should not be considered release-ready until
applicable gates are satisfied.

Possible mandatory gates:

- authentication behavior verified;
- authorization behavior verified;
- ownership tests pass;
- input validation verified;
- security tests pass;
- secret scan passes;
- dependency changes reviewed;
- SAST findings reviewed;
- resource limits verified;
- configuration validated;
- security reviewer completed;
- no unresolved BLOCKER/HIGH findings;
- MEDIUM findings resolved or explicitly accepted.

---

# 82. Runtime Monitoring

Security does not end at deployment.

Monitor relevant signals such as:

- repeated authentication failures;
- authorization denials;
- unusual upload rates;
- OCR failures;
- resource exhaustion;
- unexpected 5xx spikes;
- dependency vulnerabilities;
- suspicious API patterns.

Monitoring requirements should reflect actual feature risk.

---

# 83. Detection Without Data Leakage

Security telemetry should identify suspicious behavior without unnecessarily
capturing sensitive data.

Prefer:

request_id
user/account internal identifier where appropriate
event type
status
duration
safe resource identifier

Avoid:

raw receipt text
tokens
passwords
secret values
full authorization headers

---

# 84. Incident Response

When a real security incident is suspected:

1. preserve evidence;
2. determine affected systems;
3. contain the issue;
4. revoke/rotate credentials where required;
5. block exploit path;
6. remediate root cause;
7. verify remediation;
8. document the incident;
9. add preventive controls/tests.

Do not destroy useful evidence before understanding the incident.

---

# 85. Credential Compromise

A credential visible in:

- source control;
- screenshots;
- public logs;
- public issue;
- external chat;
- unauthorized system

should be treated as potentially compromised.

The normal response is:

rotate
→ update legitimate systems
→ revoke old credential
→ verify no unintended use

Removing the visible occurrence alone is not sufficient.

---

# 86. Root-Cause Security Fixes

Do not stop at the immediate symptom.

Example:

Production secret leaked.

Local fix:
remove it from a file.

Systemic fix:
- rotate secret;
- secret scanning;
- prevent logging;
- improve environment handling.

Security fixes should reduce the chance of recurrence.

---

# 87. Security Documentation

Maintain project-level security documentation where useful.

Recommended structure:

docs/security/
    SECURITY.md
    security-invariants.md
    data-classification.md
    threat-model.md
    secure-development-lifecycle.md
    incident-response.md
    vulnerability-management.md

    components/
        auth.md
        api.md
        mobile.md
        receipts.md
        storage.md

Do not create documentation that nobody maintains.

Security documentation must reflect actual architecture.

---

# 88. Component Security Notes

Security-sensitive components should document:

- protected assets;
- trust boundaries;
- ownership model;
- accepted input;
- limits;
- external providers;
- logging restrictions;
- known risks;
- security tests.

This is especially valuable for:

- authentication;
- file uploads;
- OCR;
- payments;
- storage;
- external integrations.

---

# 89. Security ADRs

Use Architecture Decision Records for important long-lived security decisions.

Example:

ADR: Run receipt OCR locally using Tesseract.

Document:

- context;
- security considerations;
- alternatives;
- selected solution;
- consequences;
- operational risks.

Do not create ADRs for trivial implementation details.

---

# 90. Framework Security Features

Prefer framework-provided security mechanisms over custom replacements.

Examples:

- validated request schemas;
- established authentication middleware;
- parameterized ORM queries;
- standard secure storage APIs.

Do not bypass framework security protections without a clear documented reason.

---

# 91. Security vs Usability

Security controls should not create unnecessary friction.

Choose controls proportional to the threat.

Do not add:

- arbitrary confirmations;
- unnecessary reauthentication;
- excessive complexity

without a security reason.

But usability is not a valid reason to bypass authorization or expose sensitive
data.

---

# 92. Security vs Availability

Fail closed for authorization and privilege decisions.

For non-security-critical external integrations, graceful degradation may be
appropriate.

Example:

analytics provider unavailable
→ application may continue

authentication verification unavailable
→ protected operation must not be allowed merely for availability.

---

# 93. Security vs Performance

Security checks should be efficient but must not be removed merely to improve
performance.

Measure first.

Optimize implementation while preserving the security invariant.

---

# 94. Never Trust Security Through Obscurity

Security must not depend on attackers not knowing:

- route names;
- UUIDs;
- client implementation;
- mobile bundle code;
- internal naming.

Assume attackers can inspect the client and API behavior.

---

# 95. No Security Theater

Do not add controls that look secure but do not enforce a real boundary.

Examples:

- frontend-only authorization;
- hidden admin button;
- UUID secrecy as authorization;
- MIME extension check alone;
- CORS used as authentication.

Every security control should address a concrete threat.

---

# 96. Mandatory Pre-Implementation Security Questions

Before implementing a security-relevant task, answer:

1. What assets are affected?
2. What input is untrusted?
3. Where are the trust boundaries?
4. Who owns the data?
5. How is identity established?
6. How is authorization enforced?
7. Can the operation be replayed?
8. Can concurrent requests break an invariant?
9. Can input consume excessive resources?
10. Can errors leak sensitive information?
11. Are new secrets required?
12. Are new dependencies/providers introduced?
13. What must remain true after failure?
14. What negative tests are required?
15. What should be monitored after release?

Not every trivial UI task requires a full threat model.

Use judgment based on risk.

---

# 97. Mandatory Implementation Review Questions

During implementation ask:

- Is all untrusted input validated?
- Is ownership enforced server-side?
- Are privileged fields protected from mass assignment?
- Are operations bounded?
- Are timeouts present for expensive external work?
- Are filesystem paths server-controlled?
- Are SQL/subprocess calls safe?
- Are errors sanitized?
- Are secrets absent from source/client/logs?
- Are dependencies necessary?
- Are state transitions atomic?
- Are retries safe?
- Are concurrent operations safe?
- Are secure defaults preserved?

---

# 98. Mandatory Pre-Release Security Questions

Before declaring a task ready:

- Were security invariants preserved?
- Were authorization paths tested?
- Were negative cases tested?
- Were dependency changes reviewed?
- Were secret leaks checked?
- Were security-sensitive configs validated?
- Are logs safe?
- Are resource limits appropriate?
- Are known risks documented?
- Is runtime monitoring adequate for the risk?
- Are there unresolved BLOCKER/HIGH findings?
- Are MEDIUM findings resolved or explicitly accepted?

---

# 99. Evidence Over Security Claims

Never accept:

"This is secure."

Require evidence.

Examples:

- ownership integration tests;
- actual authorization path inspection;
- secret scan result;
- dependency scan;
- negative test output;
- verified timeout;
- verified size limit;
- verified database constraint;
- actual configuration validation.

Agent confidence is not security evidence.

---

# 100. Security Definition of Done

A security-relevant feature is not done merely because functional tests pass.

It is complete only when applicable conditions are satisfied:

- threats considered;
- trust boundaries understood;
- security invariants preserved;
- authentication correct;
- authorization correct;
- ownership protected;
- input validated;
- inputs bounded;
- sensitive operations atomic where required;
- replay/concurrency addressed where relevant;
- secrets protected;
- error leakage prevented;
- dependencies reviewed;
- negative security tests pass;
- security review completed;
- no unresolved release-blocking findings;
- known accepted risks documented;
- production configuration understood;
- monitoring requirements identified.

Functional correctness without security correctness is not completion.

---

# 101. Security Standards Alignment

Security decisions should align where applicable with established practices such as:

- OWASP Application Security Verification Standard;
- OWASP Mobile Application Security Verification Standard;
- OWASP API Security guidance;
- OWASP secure-development practices;
- NIST Secure Software Development Framework;
- established platform security guidance.

These standards are references, not substitutes for understanding the actual
system threat model.

Do not mechanically apply requirements unrelated to the application.

---

# 102. Final Rule

For every meaningful change, think like both:

a legitimate user

and

an attacker controlling every untrusted input.

Ask:

"What assumption does this implementation make that an attacker could violate?"

Then either:

- remove the unsafe assumption;
- enforce it at a trusted boundary;
- test it;
- or document the accepted risk.

Security must be designed into the feature, not attached after implementation.