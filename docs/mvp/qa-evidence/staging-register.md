# Staging Register (QA-0)

Owner-approved identity of the staging environment and the production denylist, as **fingerprints only**.
Rules: [../qa-evidence-and-staging-isolation.md](../qa-evidence-and-staging-isolation.md) section 3.

Fingerprint = `fp1:` + first 16 hex characters of SHA-256 of the lower-cased `scheme://host[:port]` (default port removed),
computed with `node tools/qa/staging-fingerprint.mjs`. A fingerprint is not a secret. Never write a hostname, URL, key or
project reference in this file.

An `ACTIVE` staging entry is valid only while the denylist holds at least one entry the owner has recorded (a valid
fingerprint, `Recorded by` and a `Recorded on` date). Without it a staging match cannot rule production out, so the helper
refuses to print `VERIFIED` and the validator rejects any `VERIFIED` run or `PASS` row. The initial register, with no
`ACTIVE` entry and an empty denylist, is valid.

Status as of 2026-11-03: **no staging environment exists** (QA-1 not complete). The owner has recorded no production
fingerprint here yet. Both tables are therefore empty, and no run can be `VERIFIED`.

## Staging environments

An entry may be `ACTIVE` only when the owner has filled every column. `Approved by` is the owner's name; `Approved on` is an ISO date.

| Staging ID | Status | API origin fingerprint | Auth project fingerprint | Database host fingerprint | Approved by | Approved on |
|---|---|---|---|---|---|---|
| (none) | NOT PROVISIONED | — | — | — | — | — |

## Production denylist

The owner records the fingerprints of production endpoints here so the helper can refuse them. The value that produced a
fingerprint is never recorded.

| Fingerprint | What it identifies (class only, for example "production API") | Recorded by | Recorded on |
|---|---|---|---|
| (none) | — | — | — |
