// MF2-SR09: the guarded sign-out against the REAL @supabase/auth-js (exact
// installed version, real processLock, real events and storage), with a scripted
// GoTrue server behind auth-js's own `fetch` option.
//
// Library facts these tests pin down (auth-js 2.112.3, lock = processLock):
//  * signInWithPassword and the other sign-in calls do not take the lock;
//    signOut, refreshSession, getSession and the auto-refresh tick do.
//  * signOut reads the stored session, makes a server call, then removes
//    whatever is stored at that moment and emits SIGNED_OUT.
// Hence an ownership check in front of signOut is only sound if no OTHER
// session-changing call can run in that window: the exported client queues all
// of them (auth-gateway.ts), and the library's own background work can only move
// the stored session to a newer token of the same user or end it.
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { after, before, describe, it } from "node:test";

import { GoTrueClient } from "@supabase/supabase-js";
import type { Session } from "@supabase/supabase-js";

import { startAuthSession, type AuthClientLike } from "../features/auth/auth-session.ts";
import { createNavigationIntentStore } from "../features/auth/navigation-intent.ts";
import { queueSessionMutations, SESSION_MUTATORS, SESSION_PASSTHROUGH } from "./auth-gateway.ts";
import { createAuthOperationQueue, createGuardedSessionEnd, createQueuedRefresh } from "./auth-operations.ts";
import {
  createFakeGoTrueServer,
  createRealAuth,
  deferred,
  tick,
  type FakeServer,
} from "./auth-js-test-support.ts";
import { createFetchWithTimeout } from "./fetch-with-timeout.ts";
import { SessionBoundary } from "./session-boundary.ts";
import { createSessionLifecycle, type OwnershipProof } from "./session-lifecycle.ts";

const unhandled: unknown[] = [];
const onUnhandled = (reason: unknown) => unhandled.push(reason);

before(() => {
  process.on("unhandledRejection", onUnhandled);
});
after(() => {
  process.off("unhandledRejection", onUnhandled);
});

function lab(options: { server?: FakeServer; fetch?: typeof fetch } = {}) {
  const server = options.server ?? createFakeGoTrueServer();
  const { client: raw, store } = createRealAuth(server, { fetch: options.fetch });
  const queue = createAuthOperationQueue();
  const guarded = queueSessionMutations(raw, queue); // what the app imports
  const counts = { resets: 0 };
  const boundary = new SessionBoundary(() => {
    counts.resets += 1;
  });
  const intent = createNavigationIntentStore();
  const stop = startAuthSession<Session>({
    auth: guarded as unknown as AuthClientLike<Session>,
    boundary,
    publish: () => undefined,
  });
  const lifecycle = createSessionLifecycle({
    // The same factory lib/session-runtime.ts uses.
    refreshSession: createQueuedRefresh({
      queue,
      refresh: () => raw.refreshSession(),
      onRejected: () => intent.captureOnInvalidation(),
    }),
    endSession: createGuardedSessionEnd({
      queue,
      signOutLocal: async () => {
        await raw.signOut({ scope: "local" });
      },
    }),
  });

  async function signIn(client: GoTrueClient, who: "A" | "B") {
    const result = await client.signInWithPassword({ email: `${who}@example.test`, password: "pw" });

    if (!result.data.session) {
      throw new Error(`sign-in of ${who} failed`);
    }

    return result.data.session;
  }

  function proofFor(session: Session): OwnershipProof {
    const snapshot = boundary.snapshot();

    return {
      epoch: snapshot.epoch,
      stillOwns: () => boundary.ownsToken(snapshot, session.user.id, session.access_token),
    };
  }

  const storedUser = async () => (await raw.getSession()).data.session?.user.id ?? null;

  return { server, raw, guarded, queue, boundary, counts, intent, lifecycle, signIn, proofFor, storedUser, store, stop };
}

describe("what the library does (why the exported client must queue session changes)", () => {
  it("a sign-in OUTSIDE the queue during the sign-out erases B locally (reproduced on auth-js)", async () => {
    const w = lab();
    const sessionA = await w.signIn(w.raw, "A");

    await tick();

    const proof = w.proofFor(sessionA);
    const logoutGate = deferred<void>();

    w.server.gates.logout = logoutGate;

    const ending = createGuardedSessionEnd({
      queue: w.queue,
      signOutLocal: async () => {
        await w.raw.signOut({ scope: "local" });
      },
    })(proof); // passes stillOwns(); signOut is now waiting on its server call

    await tick(20);
    await w.signIn(w.raw, "B"); // the bypass: raw client, not through the queue
    await tick();
    assert.equal(w.boundary.snapshot().userId, "B");
    logoutGate.resolve(undefined);

    assert.equal(await ending, "signed-out");
    await tick();
    assert.equal(await w.storedUser(), null, "B's stored session was removed by A's sign-out");
    assert.equal(w.boundary.snapshot().userId, null);
    assert.deepEqual(w.server.log.logouts.map((token) => token === sessionA.access_token), [true], "only A was revoked server-side");
  });

  it("signInWithPassword does not wait for the lock that a pending signOut holds", async () => {
    const w = lab();

    await w.signIn(w.raw, "A");
    w.server.gates.logout = deferred<void>();

    const signingOut = w.raw.signOut({ scope: "local" });

    await tick(20);

    const started = Date.now();

    await w.signIn(w.raw, "B"); // completes while signOut is still waiting for its server call
    assert.ok(Date.now() - started < 500);
    w.server.gates.logout.resolve(undefined);
    await signingOut;
  });
});

describe("SR09: with the exported (queueing) client the window is closed", () => {
  it("A's 401 -> sign-out in progress -> B signs in through the client: B waits and stays signed in", async () => {
    const w = lab();
    const sessionA = await w.signIn(w.guarded, "A");

    await tick();

    const logoutGate = deferred<void>();

    w.server.gates.logout = logoutGate;

    // Against a real server a rejected refresh usually makes the library end the
    // session itself; to exercise the guarded sign-out path we drive endSession
    // directly after the confirmation, exactly like the lifecycle does.
    const ending = createGuardedSessionEnd({
      queue: w.queue,
      signOutLocal: async () => {
        await w.raw.signOut({ scope: "local" });
      },
    })(w.proofFor(sessionA));

    await tick(20);

    const signingInB = w.signIn(w.guarded, "B"); // exported client: queued behind the sign-out

    await tick(20);
    assert.equal(w.boundary.snapshot().userId, "A", "B cannot take over while A's sign-out runs");
    logoutGate.resolve(undefined);

    assert.equal(await ending, "signed-out");
    await signingInB;
    await tick();

    assert.equal(w.boundary.snapshot().userId, "B");
    assert.equal(await w.storedUser(), "B", "B's session survives");
    assert.deepEqual(w.server.log.logouts.map((token) => token === sessionA.access_token), [true]);
  });

  it("B's sign-in already running: A's queued 401 handling does nothing (no refresh, no sign-out)", async () => {
    const w = lab();
    const sessionA = await w.signIn(w.guarded, "A");

    await tick();

    const proofA = w.proofFor(sessionA);
    const passwordGate = deferred<void>();

    w.server.gates.password.set("B@example.test", passwordGate);

    const signingInB = w.signIn(w.guarded, "B"); // holds the queue, waiting on the server

    await tick(20);

    const handling = w.lifecycle.handleUnauthorized(
      { userId: "A", accessToken: sessionA.access_token },
      proofA,
    );

    await tick(20);
    passwordGate.resolve(undefined);
    await signingInB;

    assert.equal(await handling, "stale");
    assert.equal(w.server.log.refreshRequests, 0, "B's session was not refreshed on A's behalf");
    assert.deepEqual(w.server.log.logouts, []);
    assert.equal(await w.storedUser(), "B");
    assert.equal(w.boundary.snapshot().userId, "B");
  });

  it("the library's own refresh of A while the sign-out waits can only produce a newer A token", async () => {
    const w = lab();
    const sessionA = await w.signIn(w.guarded, "A");

    await tick();

    const refreshGate = deferred<void>();

    w.server.gates.refresh = refreshGate;

    const backgroundRefresh = w.raw.refreshSession(); // what the auto-refresh tick does (holds the lock)

    await tick(20);

    const ending = createGuardedSessionEnd({
      queue: w.queue,
      signOutLocal: async () => {
        await w.raw.signOut({ scope: "local" });
      },
    })(w.proofFor(sessionA)); // check passes with the OLD token; signOut waits for the lock

    await tick(20);
    refreshGate.resolve(undefined);
    await backgroundRefresh;

    assert.equal(await ending, "signed-out");
    await tick();
    assert.equal(await w.storedUser(), null, "A's (refreshed) session is ended; no other user exists to hit");
    assert.equal(w.server.log.logouts.length, 1);
    assert.notEqual(w.server.log.logouts[0], sessionA.access_token, "the refreshed token was revoked");
    assert.equal(w.boundary.snapshot().userId, null);
  });

  it("A's token refreshed (queued) around a 401: nothing signs the refreshed session out", async () => {
    const w = lab();
    const sessionA = await w.signIn(w.guarded, "A");

    await tick();

    const oldProof = w.proofFor(sessionA);

    await w.guarded.refreshSession(); // refreshed through the client: a new token for A
    await tick();
    w.server.behavior.rejectRefresh = true;

    const outcome = await w.lifecycle.handleUnauthorized(
      { userId: "A", accessToken: sessionA.access_token },
      oldProof,
    );

    assert.equal(outcome, "stale", "the 401 belongs to the superseded token");
    assert.deepEqual(w.server.log.logouts, []);
    assert.equal(await w.storedUser(), "A");
  });

  it("A -> B -> A with the first generation's proof: stale, the later A is untouched", async () => {
    const w = lab();
    const firstA = await w.signIn(w.guarded, "A");

    await tick();

    const oldProof = w.proofFor(firstA);

    await w.signIn(w.guarded, "B");
    await w.signIn(w.guarded, "A");
    await tick();
    w.server.behavior.rejectRefresh = true;

    const outcome = await w.lifecycle.handleUnauthorized(
      { userId: "A", accessToken: firstA.access_token },
      oldProof,
    );

    assert.equal(outcome, "stale");
    assert.equal(w.server.log.refreshRequests, 0);
    assert.deepEqual(w.server.log.logouts, []);
    assert.equal(await w.storedUser(), "A");
    assert.equal(w.counts.resets, 2, "exactly the A->B and B->A rotations, none from the stale 401");
  });

  it("a genuinely invalid current session ends (the library may end it itself), with the intent kept for A only", async () => {
    const w = lab();
    const sessionA = await w.signIn(w.guarded, "A");

    await tick();
    w.intent.track("A", "/goals/42");
    w.server.behavior.rejectRefresh = true;

    const outcome = await w.lifecycle.handleUnauthorized(
      { userId: "A", accessToken: sessionA.access_token },
      w.proofFor(sessionA),
    );

    assert.ok(outcome === "signed-out" || outcome === "stale", `outcome: ${outcome}`);
    await tick();
    assert.equal(await w.storedUser(), null);
    assert.equal(w.boundary.snapshot().userId, null);
    assert.equal(w.counts.resets, 1);
    assert.equal(w.intent.consumeFor("B"), null, "another user never gets A's location");
  });

  it("concurrent 401s share one investigation", async () => {
    const w = lab();
    const sessionA = await w.signIn(w.guarded, "A");

    await tick();
    w.server.behavior.rejectRefresh = true;

    const proof = w.proofFor(sessionA);
    const outcomes = await Promise.all(
      Array.from({ length: 6 }, () =>
        w.lifecycle.handleUnauthorized({ userId: "A", accessToken: sessionA.access_token }, proof),
      ),
    );

    assert.equal(new Set(outcomes).size, 1);
    assert.equal(w.server.log.refreshRequests, 1);
    assert.ok(w.server.log.logouts.length <= 1);
    assert.equal(w.boundary.snapshot().userId, null);
  });

  it("no stale navigation or cache reset: switching A -> B causes one rotation and drops A's intent", async () => {
    const w = lab();
    const sessionA = await w.signIn(w.guarded, "A");

    await tick();
    w.intent.track("A", "/receipts/9");
    w.intent.captureOnInvalidation();
    await w.signIn(w.guarded, "B");
    await tick();

    assert.equal(w.counts.resets, 1);
    assert.equal(w.intent.consumeFor("B"), null);
    assert.equal(sessionA.user.id, "A");
  });

  it("everything at once completes without deadlock or unhandled rejections", async () => {
    const w = lab();
    const sessionA = await w.signIn(w.guarded, "A");

    await tick();
    w.server.behavior.rejectRefresh = false;

    const results = await Promise.race([
      Promise.allSettled([
        w.signIn(w.guarded, "B"),
        w.guarded.signOut(),
        w.lifecycle.handleUnauthorized({ userId: "A", accessToken: sessionA.access_token }, w.proofFor(sessionA)),
        w.guarded.refreshSession(),
        w.guarded.getSession(),
        w.signIn(w.guarded, "A"),
      ]),
      tick(3000).then(() => "deadlock" as const),
    ]);

    assert.notEqual(results, "deadlock");
    await tick(50);
    assert.deepEqual(unhandled, []);
  });

  it("a hung server call cannot block the queue forever (request timeout), and the session is still cleared", async () => {
    const server = createFakeGoTrueServer();
    const w = lab({ server, fetch: createFetchWithTimeout(server.fetch, 60) });
    const sessionA = await w.signIn(w.guarded, "A");

    await tick();
    server.behavior.hangLogout = true;

    const startedAt = Date.now();
    const ending = createGuardedSessionEnd({
      queue: w.queue,
      signOutLocal: async () => {
        await w.raw.signOut({ scope: "local" });
      },
    })(w.proofFor(sessionA));
    const signingInB = w.signIn(w.guarded, "B");

    assert.equal(await ending, "signed-out");
    await signingInB;

    assert.ok(Date.now() - startedAt < 2000, "released by the request timeout");
    assert.equal(await w.storedUser(), "B");
    assert.equal(w.boundary.snapshot().userId, "B");
  });
});

describe("the gateway", () => {
  it("every public method of the installed GoTrueClient is classified (an upgrade adding one fails here)", () => {
    const publicNames = Object.getOwnPropertyNames(GoTrueClient.prototype).filter(
      (name) => !name.startsWith("_") && name !== "constructor",
    );
    const classified = new Set([...SESSION_MUTATORS, ...SESSION_PASSTHROUGH]);

    assert.deepEqual(publicNames.filter((name) => !classified.has(name)), [], "unclassified auth-js methods");
    assert.deepEqual([...classified].filter((name) => !publicNames.includes(name)), [], "classification lists a method auth-js does not have");
    assert.equal([...SESSION_MUTATORS].filter((name) => SESSION_PASSTHROUGH.has(name)).length, 0);
  });

  it("queues mutators in call order, passes everything else through bound, and survives a failing call", async () => {
    const order: string[] = [];
    const target = {
      async signInWithPassword(label: string) {
        order.push(`start:${label}`);
        await tick(10);
        order.push(`end:${label}`);

        return label;
      },
      async signOut() {
        throw new Error("sign-out failed");
      },
      getSession() {
        return "read";
      },
      field: 7,
    };
    const guarded = queueSessionMutations(target, createAuthOperationQueue());
    const first = guarded.signInWithPassword("one");
    const second = guarded.signInWithPassword("two");

    assert.equal(guarded.getSession(), "read", "reads are not queued");
    assert.equal(guarded.field, 7);
    assert.deepEqual([await first, await second], ["one", "two"]);
    assert.deepEqual(order, ["start:one", "end:one", "start:two", "end:two"]);
    await assert.rejects(guarded.signOut());
    assert.equal(await guarded.signInWithPassword("three"), "three", "the queue survived the failure");
  });
});

describe("structural: nothing can bypass the queue", () => {
  function sources(root: string): string[] {
    return (readdirSync(root, { recursive: true }) as string[])
      .map((entry) => join(root, entry))
      .filter((path) => /\.(ts|tsx)$/.test(path))
      .filter((path) => !/\.test\.ts$/.test(path) && !/test-support\.ts$/.test(path));
  }

  function usersOf(token: string): string[] {
    return [...sources("src"), ...sources("app")]
      .filter((path) => readFileSync(path, "utf8").includes(token))
      .map((path) => path.replace(/\\/g, "/"))
      .sort();
  }

  it("the unguarded client is imported only by the session runtime (and defined in supabase.ts)", () => {
    assert.deepEqual(usersOf("rawSupabase"), ["src/lib/session-runtime.ts", "src/lib/supabase.ts"]);
  });

  it("only supabase.ts creates a Supabase client", () => {
    assert.deepEqual(usersOf("createClient("), ["src/lib/supabase.ts"]);
  });

  it("auth MFA (which upgrades a session) is not used", () => {
    assert.deepEqual(usersOf("auth.mfa"), []);
  });
});
