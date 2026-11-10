// MF-4: a local sign-out is only "done" when the session is really gone.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { createGuardedSessionEnd, createAuthOperationQueue, createVerifiedLocalSignOut } from "../../api/auth-operations.ts";

describe("createVerifiedLocalSignOut", () => {
  it("resolves when auth reports no error and nobody is current", async () => {
    await createVerifiedLocalSignOut({ signOutLocal: async () => ({ error: null }), currentUserId: () => null })();
  });

  it("throws the auth error (expired stored session, server unreachable): nothing was removed", async () => {
    const failure = { name: "AuthRetryableFetchError", status: 0 };

    await assert.rejects(createVerifiedLocalSignOut({ signOutLocal: async () => ({ error: failure }), currentUserId: () => "u-1" }), (error) => error === failure);
  });

  it("throws when the call reported success but the session is still current", async () => {
    await assert.rejects(createVerifiedLocalSignOut({ signOutLocal: async () => ({ error: null }), currentUserId: () => "u-1" }));
  });

  it("through the guarded end: a failed sign-out is a rejection, never 'signed-out'", async () => {
    const end = createGuardedSessionEnd({
      queue: createAuthOperationQueue(),
      signOutLocal: createVerifiedLocalSignOut({ signOutLocal: async () => ({ error: new Error("x") }), currentUserId: () => "u-1" }),
    });

    await assert.rejects(end({ epoch: 1, stillOwns: () => true }));
    assert.equal(await end({ epoch: 1, stillOwns: () => false }), "stale", "a stale proof never even tries");
  });
});
