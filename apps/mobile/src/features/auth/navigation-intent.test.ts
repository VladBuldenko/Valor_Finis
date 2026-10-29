import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { createNavigationIntentStore, sanitizeReturnPath } from "./navigation-intent.ts";

describe("sanitizeReturnPath", () => {
  for (const path of ["/goals", "/goals/3f2a9c1e-7b1d-4c58-9d0e-1a2b3c4d5e6f", "/expenses/new", "/income/edit_1"]) {
    it(`accepts ${path}`, () => {
      assert.equal(sanitizeReturnPath(path), path);
    });
  }

  const unsafe: unknown[] = [
    "",
    "/",
    "goals",
    "//evil.example/steal",
    "https://evil.example",
    "javascript:alert(1)",
    "/goals?token=abc",
    "/goals#access_token=abc",
    "/goals/../sign-in",
    "/goals/%2e%2e/admin",
    "/go als",
    "/goals\\evil",
    "/sign-in",
    "/sign-in/reset",
    "/" + "a".repeat(250),
    null,
    undefined,
    42,
    { path: "/goals" },
  ];

  for (const path of unsafe) {
    it(`rejects ${JSON.stringify(path)?.slice(0, 40)}`, () => {
      assert.equal(sanitizeReturnPath(path), null);
    });
  }
});

describe("navigation intent store", () => {
  it("restores the last location after the server ended the session, for the same user", () => {
    const store = createNavigationIntentStore();

    store.track("user-a", "/goals");
    store.track("user-a", "/goals/42");
    store.captureOnInvalidation();

    assert.equal(store.consumeFor("user-a"), "/goals/42");
  });

  it("restores only once", () => {
    const store = createNavigationIntentStore();

    store.track("user-a", "/goals");
    store.captureOnInvalidation();
    store.consumeFor("user-a");

    assert.equal(store.consumeFor("user-a"), null);
  });

  it("never restores another user's location, and erases it", () => {
    const store = createNavigationIntentStore();

    store.track("user-a", "/goals/42");
    store.captureOnInvalidation();

    assert.equal(store.consumeFor("user-b"), null);
    assert.equal(store.consumeFor("user-a"), null);
  });

  it("restores nothing after a deliberate sign-out", () => {
    const store = createNavigationIntentStore();

    store.track("user-a", "/goals/42");
    store.discard();
    store.captureOnInvalidation();

    assert.equal(store.consumeFor("user-a"), null);
  });

  it("ignores unsafe paths while tracking and keeps the last safe one", () => {
    const store = createNavigationIntentStore();

    store.track("user-a", "/goals");
    store.track("user-a", "//evil.example");
    store.track("user-a", "/goals?token=1");
    store.captureOnInvalidation();

    assert.equal(store.consumeFor("user-a"), "/goals");
  });

  it("restores nothing when no location was tracked", () => {
    const store = createNavigationIntentStore();

    store.captureOnInvalidation();
    assert.equal(store.consumeFor("user-a"), null);
  });

  it("expires after 30 minutes", () => {
    let clock = 1_000;
    const store = createNavigationIntentStore(() => clock);

    store.track("user-a", "/goals");
    store.captureOnInvalidation();
    clock += 30 * 60 * 1000 + 1;

    assert.equal(store.consumeFor("user-a"), null);
  });

  it("still restores just inside the expiry window", () => {
    let clock = 1_000;
    const store = createNavigationIntentStore(() => clock);

    store.track("user-a", "/goals");
    store.captureOnInvalidation();
    clock += 30 * 60 * 1000;

    assert.equal(store.consumeFor("user-a"), "/goals");
  });

  it("does not keep a tracked location across an invalidation capture", () => {
    const store = createNavigationIntentStore();

    store.track("user-a", "/goals");
    store.captureOnInvalidation();
    store.captureOnInvalidation(); // nothing tracked since: nothing pending

    assert.equal(store.consumeFor("user-a"), null);
  });
});
