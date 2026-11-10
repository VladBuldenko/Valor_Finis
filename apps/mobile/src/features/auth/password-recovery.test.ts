// MF-4: setting the new password. Fakes only; the ownership/queue behavior is
// tested on the real auth library in auth-recovery-integration.test.ts.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { AUTH_NETWORK_MESSAGE, AUTH_RATE_LIMIT_MESSAGE } from "./auth-registration.ts";
import { updateRecoveredPassword, type GuardedUpdateResult } from "./password-recovery.ts";

const PASSWORD = "brand new secret 123";
const api = (code: string, status = 400) => ({ name: "AuthApiError", code, status, message: `SERVER ${code} ${PASSWORD}` });

function run(result: GuardedUpdateResult | (() => never), isCurrent = true) {
  const calls: string[] = [];
  const promise = updateRecoveredPassword(
    {
      update: async (password) => {
        calls.push(password);

        return typeof result === "function" ? result() : result;
      },
      isCurrent: () => isCurrent,
    },
    PASSWORD,
  );

  return { calls, promise };
}

describe("updateRecoveredPassword", () => {
  it("success", async () => {
    const w = run({ status: "done", error: null });

    assert.deepEqual(await w.promise, { kind: "updated" });
    assert.deepEqual(w.calls, [PASSWORD], "exactly one call");
  });

  it("stale: the ownership check failed inside the queue", async () => {
    assert.deepEqual(await run({ status: "stale" }).promise, { kind: "stale" });
  });

  it("a change that succeeded is reported even if the screen is gone (the recovery must still end)", async () => {
    assert.deepEqual(await run({ status: "done", error: null }, false).promise, { kind: "updated" });
  });

  it("a failure of a departed screen is dropped", async () => {
    assert.deepEqual(await run({ status: "done", error: api("weak_password") }, false).promise, { kind: "stale" });
  });

  it("weak password: fixed phrases, never the server's text", async () => {
    assert.deepEqual(await run({ status: "done", error: { name: "AuthWeakPasswordError", code: "weak_password", reasons: ["length"] } }).promise, {
      kind: "rejected",
      message: "That password is not strong enough: make it longer.",
    });
    assert.deepEqual(await run({ status: "done", error: api("weak_password", 422) }).promise, {
      kind: "rejected",
      message: "That password is not strong enough. Try a longer one with a mix of characters.",
    });
  });

  it("the same password as before", async () => {
    assert.deepEqual(await run({ status: "done", error: api("same_password", 422) }).promise, {
      kind: "rejected",
      message: "Choose a password that is different from your current one.",
    });
  });

  it("an expired or revoked recovery session needs a new link", async () => {
    for (const code of ["session_not_found", "session_expired", "bad_jwt"]) {
      assert.deepEqual(await run({ status: "done", error: api(code, 401) }).promise, { kind: "session_expired" }, code);
    }

    assert.deepEqual(await run({ status: "done", error: { name: "AuthSessionMissingError" } }).promise, { kind: "session_expired" });
  });

  it("rate limit, network (outcome unknown, said so) and unknown failures", async () => {
    assert.deepEqual(await run({ status: "done", error: api("over_request_rate_limit", 429) }).promise, { kind: "failed", message: AUTH_RATE_LIMIT_MESSAGE });
    assert.deepEqual(await run({ status: "done", error: { name: "AuthRetryableFetchError", status: 0 } }).promise, {
      kind: "failed",
      message: `${AUTH_NETWORK_MESSAGE} We could not confirm whether the password was changed.`,
    });
    assert.deepEqual(await run({ status: "done", error: api("mystery") }).promise, { kind: "failed", message: "We could not change your password. Please try again." });
    assert.deepEqual(await run(() => { throw new Error(PASSWORD); }).promise, { kind: "failed", message: "We could not change your password. Please try again." });
  });

  it("no outcome carries the password or the server's text", async () => {
    const outcomes = [];

    for (const code of ["weak_password", "same_password", "session_not_found", "mystery", "over_request_rate_limit"]) {
      outcomes.push(await run({ status: "done", error: api(code) }).promise);
    }

    assert.doesNotMatch(JSON.stringify(outcomes), /SERVER|brand new secret/);
  });
});
