---
name: git-pr-workflow
description: Safely moves completed work through branch creation, explicit staging, commit, push, pull request, CI verification, and merge without losing or mixing unrelated changes.
---

# Git PR Workflow

Use this skill when preparing completed work for Git history, pull request, CI, and merge.

## Goal

Keep every task isolated, reviewable, reversible, and safe while preserving unrelated user work.

## Workflow

### 1. Inspect Git state first

Before any Git write operation, inspect:

- current branch;
- working tree;
- staged changes;
- recent commits;
- remote tracking state when relevant.

Use read-only commands first.

Never assume the repository is clean.

### 2. Keep one task per branch

Prefer:

`main`
→ task branch
→ commit
→ pull request
→ CI
→ merge

Use branch names such as:

- `feat/VF-XXX-short-name`
- `fix/VF-XXX-short-name`
- `chore/VF-XXX-short-name`

Do not mix unrelated business tasks in one branch.

### 3. Preserve unrelated work

Never discard, overwrite, or silently include unrelated changes.

Do not use destructive commands to make the working tree clean.

Do not run:

- `git reset --hard`;
- force push;
- destructive restore;
- rebase;
- stash;

unless the user explicitly authorizes the exact operation.

If unrelated changes exist, isolate the task safely before proceeding.

### 4. Stage explicit files only

Never use:

`git add .`

Stage only files that belong to the current task.

Use explicit paths.

After staging, inspect exactly what will be committed.

Verify:

- staged filenames;
- staged diff;
- no unrelated files;
- no secrets;
- no debug artifacts.

### 5. Use clear commits

Prefer one coherent commit for one coherent MVP task when practical.

Commit format:

`<type>(<scope>): [VF-XXX] short description`

Examples:

`feat(expenses): [VF-002] add expense edit and delete`

`fix(categories): [VF-004] prevent duplicate bootstrap`

`chore(ai): [VF-003] add agent workflow`

Use:

- `feat` for new behavior;
- `fix` for defect fixes;
- `chore` for infrastructure/tooling;
- `test` for test-only work;
- `refactor` only when behavior intentionally remains unchanged.

Do not create meaningless commits such as:

- `fix`;
- `changes`;
- `update`;
- `work`.

### 6. Verify the commit before push

After committing, inspect:

- commit message;
- files in the commit;
- current status;
- branch position.

Confirm the commit contains only the intended task.

Do not push if the commit accidentally contains unrelated work.

### 7. Push the task branch

Push only the intended feature branch.

Do not push directly to `main` for normal feature development.

Set upstream tracking when pushing a new branch.

After push, verify the local branch tracks the expected remote branch.

### 8. Create a focused pull request

Pull request:

Base:
`main`

Compare:
current task branch

Use a concise title:

`[VF-XXX] Short task name`

Use a short description:

- what changed;
- verification result.

Example:

`Adds expense edit and delete flows with backend coverage and mobile query invalidation.`

`Verification: backend tests passed, TypeScript clean, lint passed.`

Do not add unnecessary long descriptions unless the change requires explanation.

### 9. Verify PR scope

Before merge, inspect the PR diff.

Confirm:

- only intended commits are present;
- only intended files changed;
- no previous unfinished task is included;
- no infrastructure or unrelated cleanup leaked into the PR.

If the PR contains another task, do not merge until branch ancestry or task isolation is corrected.

### 10. Wait for CI

Do not treat local success as a replacement for CI.

Verify required checks such as:

- tests;
- migrations;
- typecheck;
- lint;
- build;

depending on configured workflows.

If CI fails:

- inspect the actual failure;
- reproduce locally when possible;
- fix the root cause;
- rerun verification;
- push the fix.

Do not bypass failing required checks.

### 11. Verify review state

Before merge, confirm:

- material reviewer findings are resolved;
- required manual E2E is complete or explicitly documented;
- no CRITICAL or HIGH unresolved issue remains;
- release verification reports an acceptable readiness state.

Use the `release-verification` skill before final merge readiness.

### 12. Merge deliberately

Merge only after:

- PR scope is correct;
- CI is green;
- required review is complete;
- required verification is complete;
- the user has authorized merge.

Do not merge automatically unless the user explicitly requests it.

### 13. Update local repository after merge

After remote merge, update local branch information before starting dependent work.

Inspect the current working tree before switching branches or synchronizing `main`.

Do not lose uncommitted work while updating local state.

### 14. Start the next task from the correct base

New independent work should normally branch from the updated `main`.

If a task intentionally depends on an unmerged task, treat it as a stacked dependency and make that dependency explicit.

Do not accidentally build unrelated tasks on top of unfinished branches.

## Safety rules

Always:

- inspect before writing;
- preserve user work;
- stage explicit files;
- verify staged diff;
- keep tasks isolated;
- verify CI before merge.

Never:

- use `git add .`;
- force push without explicit authorization;
- reset or discard user changes;
- push directly to `main` for normal feature work;
- mix unrelated tasks in one commit;
- merge with known material failures.

## Definition of done

Git workflow is complete only when:

Task branch
→ verified commit
→ remote branch
→ focused pull request
→ green CI
→ required review
→ release verification
→ authorized merge

The repository must remain in a known, recoverable state throughout the process.