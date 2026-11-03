"""
Staging-only operations tooling (VF-QA-1).

What:
    Identity guard, empty-database bootstrap, explicit reset and deterministic
    seed for the isolated staging environment.

Why:
    Every mutating staging operation must prove which database it is about to
    change before it changes anything. Nothing in `app/` imports this package,
    so the running API never loads it. Design and runbook:
    docs/operations/staging/staging-architecture-and-runbook.md.
"""
