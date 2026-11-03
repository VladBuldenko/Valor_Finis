# Waiver Register (QA-0)

Gate BR-5 of [../mvp-readiness-gates.md](../mvp-readiness-gates.md) allows exactly one waiver: **J18** (execution history,
P1), under GAP-20, signed by the owner. A waiver removes only the waived element of the journey's checklist.

Rules:
- There is **no automatic waiver**. A row is `WAIVED` only when its Waiver reference names an entry below with status `SIGNED`.
- Only the product owner signs. The tester, the engineer and Claude never add a `SIGNED` entry on the owner's behalf.
- Every entry needs: the waiver ID (`WAIVER-J18-<n>`), the journey (`J18` only), the authority (`BR-5; GAP-20`), the platforms
  covered, the exact element waived, the reason, the owner's name, the signing date (ISO), and the decision-record reference
  where the owner's written decision lives.
- The `Platforms` cell lists exactly the platforms the waiver covers: `iOS`, `Android` or `iOS; Android`. A waived row is
  accepted only on a platform the entry lists, so an iOS-only waiver never covers the Android row (and the reverse).
  Anything else in the cell (empty, "all", an unknown name) is rejected.
- The validator checks that the entry exists and is complete. It cannot verify that the owner really signed; the owner
  reviews the commit that adds a `SIGNED` entry.

Status as of 2026-11-03: **no waiver exists.** J18 is buildable (F6 is merged), so it is a normal `NOT RUN` row.

## Register

| Waiver ID | Journey | Authority | Platforms | Waived element | Reason | Owner | Signed on | Decision record reference | Status |
|---|---|---|---|---|---|---|---|---|---|
| (none) | — | — | — | — | — | — | — | — | NONE |
