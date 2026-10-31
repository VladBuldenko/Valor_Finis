// Structural guard (MF2-SR02 / SR08): only the auth coordinator may change the
// session boundary, and only through an authority claimed by startAuthSession.
// Request code (transport, lifecycle, client) must never touch the mutators.
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

function sources(root: string): string[] {
  return (readdirSync(root, { recursive: true }) as string[])
    .map((entry) => join(root, entry))
    .filter((path) => /\.(ts|tsx)$/.test(path))
    .filter((path) => !/\.test\.ts$/.test(path) && !/(-support|test-support)\.ts$/.test(path));
}

function usersOf(token: string): string[] {
  return [...sources("src"), ...sources("app")]
    .filter((path) => readFileSync(path, "utf8").includes(token))
    .map((path) => path.replace(/\\/g, "/"))
    .sort();
}

describe("who may change the session boundary", () => {
  it("applyAuthEvent appears only in the boundary and the coordinator", () => {
    assert.deepEqual(usersOf("applyAuthEvent"), [
      "src/api/session-boundary.ts",
      "src/features/auth/auth-coordinator.ts",
    ]);
  });

  it("claimAuthority is called only by the auth session effect", () => {
    assert.deepEqual(usersOf("claimAuthority"), [
      "src/api/session-boundary.ts",
      "src/features/auth/auth-session.ts",
    ]);
  });

  it("the removed request-local observation does not come back", () => {
    assert.deepEqual(usersOf(".observe("), []);
  });
});
