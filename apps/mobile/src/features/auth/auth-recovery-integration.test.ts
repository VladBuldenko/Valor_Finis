// MF-4 on the REAL @supabase/auth-js (installed version, PKCE flow like the app, real
// processLock, events and storage) behind the app's real queue/gateway, session
// boundary, coordinator, recovery state and link handler. A scripted GoTrue server
// answers through auth-js's own `fetch` option. Nothing here talks to a network or
// to Supabase.
//
// What it proves that the fake-based tests cannot: that setSession / updateUser /
// sign-in really interleave the way the ownership checks assume, and that the
// boundary, the recovery state and the cache reset agree.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { GoTrueClient, processLock } from "@supabase/supabase-js";
import type { Session } from "@supabase/supabase-js";

import { queueSessionMutations } from "../../api/auth-gateway.ts";
import {
  createAuthOperationQueue,
  createGuardedPasswordUpdate,
  createGuardedSessionEnd,
  createVerifiedLocalSignOut,
} from "../../api/auth-operations.ts";
import { createFakeGoTrueServer, deferred, tick } from "../../api/auth-js-test-support.ts";
import { SessionBoundary } from "../../api/session-boundary.ts";
import type { OwnershipProof } from "../../api/session-lifecycle.ts";
import { createAuthLinkHandler, type LinkAuth } from "./auth-link-handler.ts";
import { startAuthSession, type AuthClientLike } from "./auth-session.ts";
import { updateRecoveredPassword } from "./password-recovery.ts";
import { createRecoveryPersistence } from "./recovery-persistence.ts";
import { createRecoveryState, decideRootRoute } from "./recovery-state.ts";
import { bindRecoveryPersistence, createStartupResolver } from "./recovery-startup.ts";
import { memoryStorage } from "./recovery-test-support.ts";

const b64 = (value: unknown) => Buffer.from(JSON.stringify(value)).toString("base64url");
let serial = 0;

function jwt(sub: string, expiresInSeconds = 3600): string {
  serial += 1;

  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub, role: "authenticated", serial, exp: Math.floor(Date.now() / 1000) + expiresInSeconds })}.sig`;
}

const userJson = (id: string) => ({ id, aud: "authenticated", email: `${id}@example.test`, app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" });
const json = (status: number, body: unknown) =>
  new Response(body === null ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

// Everything that outlives a process: the scripted server, auth-js's storage (the
// persisted session and PKCE verifier) and the recovery record. `lab(world)` boots a
// "process" on top of it; `restart` kills one (no cleanup) and boots the next.
function newWorld() {
  return {
    server: createFakeGoTrueServer(),
    authStore: new Map<string, string>(),
    marker: memoryStorage(),
    puts: [] as { bearer: string; password: string }[],
    validAccess: new Set<string>(),
    // PKCE codes the scripted server will exchange: code -> user id.
    codes: new Map<string, string>(),
    requests: { recover: 0, signUp: 0, exchanges: 0 },
    holdPut: { gate: null as ReturnType<typeof deferred<void>> | null },
    // Local sign-outs fail the way auth-js reports an unreachable server with an
    // expired stored session: `{ error }`, and nothing is removed.
    signOutFails: { on: false },
    // The next PKCE exchange waits for the test (models an attempt that is in flight).
    holdExchange: { gate: null as ReturnType<typeof deferred<void>> | null },
    // The next restore fails the way auth-js reports an unreachable auth server (the
    // session stays in storage but is not returned). Real auth-js would retry for up to
    // 30 s first, which a deterministic test cannot wait for.
    storeFail: { on: false },
    // refresh token -> user id, for sessions this scripted server issued over PKCE.
    refreshOwners: new Map<string, string>(),
  };
}

type World = ReturnType<typeof newWorld>;

function lab(world: World = newWorld()) {
  const { server, puts, validAccess, codes, requests, holdPut } = world;
  const fetchImpl = async (input: unknown, init: RequestInit = {}): Promise<Response> => {
    const url = new URL(String(input));

    if (url.pathname.endsWith("/token") && url.searchParams.get("grant_type") === "refresh_token") {
      const owner = world.refreshOwners.get((JSON.parse(String(init.body)) as { refresh_token: string }).refresh_token);

      if (owner) {
        serial += 1;

        const access = jwt(owner);
        const refresh = `pkce-refresh-${owner}-${serial}`;

        validAccess.add(access);
        world.refreshOwners.set(refresh, owner);

        return json(200, { access_token: access, token_type: "bearer", expires_in: 3600, refresh_token: refresh, user: userJson(owner) });
      }
    }

    if (url.pathname.endsWith("/user")) {
      const bearer = (new Headers(init.headers).get("Authorization") ?? "").replace("Bearer ", "");
      const sub = JSON.parse(Buffer.from(bearer.split(".")[1] ?? "e30", "base64url").toString()).sub as string;

      if (!validAccess.has(bearer)) {
        return json(401, { code: "bad_jwt", message: "invalid JWT" });
      }

      if ((init.method ?? "GET") === "PUT") {
        await holdPut.gate?.promise;
        puts.push({ bearer, password: (JSON.parse(String(init.body)) as { password: string }).password });
      }

      return json(200, userJson(sub));
    }

    if (url.pathname.endsWith("/recover")) {
      requests.recover += 1;

      return json(200, {});
    }

    if (url.pathname.endsWith("/signup")) {
      requests.signUp += 1;

      return json(200, userJson("pending-user"));
    }

    if (url.pathname.endsWith("/token") && url.searchParams.get("grant_type") === "pkce") {
      requests.exchanges += 1;
      await world.holdExchange.gate?.promise;

      const body = JSON.parse(String(init.body)) as { auth_code: string; code_verifier: string };
      const userId = codes.get(body.auth_code);

      if (!userId || !body.code_verifier) {
        return json(404, { code: "flow_state_not_found", message: "flow state not found" });
      }

      codes.delete(body.auth_code); // a code works once
      serial += 1;

      const access = jwt(userId);
      const refresh = `pkce-refresh-${userId}-${serial}`;

      validAccess.add(access);
      world.refreshOwners.set(refresh, userId);

      return json(200, { access_token: access, token_type: "bearer", expires_in: 3600, refresh_token: refresh, user: userJson(userId) });
    }

    return server.fetch(input as string, init);
  };

  const store = world.authStore;
  const raw = new GoTrueClient({
    url: "https://auth.test",
    headers: { apikey: "test-publishable-key" },
    storageKey: "sb-test-auth-token",
    storage: { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => { store.set(k, v); }, removeItem: (k) => { store.delete(k); } },
    persistSession: true,
    flowType: "pkce",
    autoRefreshToken: false,
    detectSessionInUrl: false,
    lock: processLock,
    fetch: fetchImpl as typeof fetch,
  });
  const queue = createAuthOperationQueue();
  const guarded = queueSessionMutations(raw, queue);
  const counts = { resets: 0 };
  const boundary = new SessionBoundary(() => { counts.resets += 1; });
  // Exactly as the app wires it: closed until the startup resolution has run.
  const recovery = createRecoveryState({ initialPhase: "resolving" });
  const persistence = createRecoveryPersistence(world.marker.storage);

  bindRecoveryPersistence(recovery, persistence);

  const route = () => decideRootRoute({ isLoading: false, userId: boundary.snapshot().userId, recovery: recovery.getSnapshot() });
  // Every route the navigator could have shown, in order. Rules evaluation and the data
  // screens exist only in the "app" route (useAppUserId), so this is also their log.
  const routeLog: string[] = [];
  const published: (Session | null)[] = [];
  // As lib/session-runtime.ts's endSessionVerified: it throws unless the session is gone.
  const endSession = createGuardedSessionEnd({
    queue,
    signOutLocal: createVerifiedLocalSignOut({
      signOutLocal: async () => (world.signOutFails.on ? { error: { name: "AuthRetryableFetchError", status: 0 } } : raw.signOut({ scope: "local" })),
      currentUserId: () => boundary.snapshot().userId,
    }),
  });
  // Exactly the runtime's resolver (lib/auth-link-runtime.ts).
  const resolver = createStartupResolver({
    persistence,
    recovery,
    currentUserId: () => boundary.snapshot().userId,
    endRestoredSession: (userId) => {
      const snapshot = boundary.snapshot();

      return endSession({ epoch: snapshot.epoch, stillOwns: () => boundary.ownsSession(snapshot, userId) });
    },
  });
  let restoreFailed = false;

  recovery.subscribe(() => routeLog.push(route()));

  const restoringAuth = {
    getSession: async () => {
      if (world.storeFail.on) {
        return { data: { session: null }, error: { name: "AuthRetryableFetchError", status: 0 } };
      }

      return guarded.getSession();
    },
    onAuthStateChange: (callback: Parameters<typeof guarded.onAuthStateChange>[0]) => guarded.onAuthStateChange(callback),
  };
  const stop = startAuthSession<Session>({
    auth: restoringAuth as unknown as AuthClientLike<Session>,
    boundary,
    publish: ({ session, isLoading }) => {
      recovery.reconcile(session?.user.id ?? null);
      published.push(session);

      // As the auth provider does, in the same order: every settled state goes to the
      // resolver BEFORE the new session is handed to React, so what renders next already
      // sees the closed state.
      if (!isLoading) {
        resolver.onAuthState(session?.user.id ?? null, restoreFailed);
      }

      routeLog.push(route());
    },
    onRestoreError: () => {
      restoreFailed = true;
    },
  });
  const linkAuth: LinkAuth = {
    exchangeCodeForSession: async (code) => {
      const { data, error } = await guarded.exchangeCodeForSession(code);
      const redirectType = (data as { redirectType?: unknown }).redirectType;

      return { data: { session: data.session, redirectType: typeof redirectType === "string" ? redirectType : null }, error };
    },
  };
  const handler = createAuthLinkHandler({
    parse: { schemes: ["valorfinis"] },
    auth: linkAuth,
    currentUserId: () => boundary.snapshot().userId,
    recovery,
    beforeExchange: (context) => persistence.writeVerifying(context),
  });
  const updatePassword = createGuardedPasswordUpdate({
    queue,
    update: (password) => guarded.updateUser({ password }),
  });

  // The app is ready once the startup resolution has run and its record writes landed.
  async function settled(): Promise<void> {
    await new Promise<void>((resolve) => {
      const check = () => {
        if (recovery.getSnapshot().phase !== "resolving") {
          unsubscribe();
          resolve();
        }
      };
      const unsubscribe = recovery.subscribe(check);

      check();
    });
    await resolver.whenDone();
    await persistence.read(); // waits for queued record writes
  }

  // A link for a request THIS device made (the verifier is stored by auth-js).
  async function recoveryRequest(): Promise<void> {
    const { error } = await guarded.resetPasswordForEmail("person@example.test", { redirectTo: "valorfinis://auth/callback" });

    assert.equal(error, null);
  }

  async function signUpRequest(): Promise<void> {
    const { error } = await guarded.signUp({ email: "person@example.test", password: "a brand new password", options: { emailRedirectTo: "valorfinis://auth/callback" } });

    assert.equal(error, null);
  }

  function linkFor(userId: string, options: { valid?: boolean } = {}): string {
    serial += 1;

    const code = `code-${userId}-${serial}`;

    if (options.valid !== false) {
      codes.set(code, userId);
    }

    return `valorfinis://auth/callback?code=${code}`;
  }

  function proofFor(): { proof: OwnershipProof; userId: string } {
    const snapshot = boundary.snapshot();
    const userId = snapshot.userId as string;

    return { userId, proof: { epoch: snapshot.epoch, stillOwns: () => boundary.ownsSession(snapshot, userId) } };
  }

  const signIn = (id: string) => guarded.signInWithPassword({ email: `${id}@example.test`, password: "pw" });
  const authorize = (access: string) => validAccess.add(access);

  // Mirrors the service: the password change, then the recovery ends for that user.
  async function setPassword(password: string) {
    const owned = proofFor();
    const outcome = await updateRecoveredPassword({ update: (value) => updatePassword(owned.proof, value), isCurrent: () => true }, password);

    if (outcome.kind === "updated" && owned.proof.stillOwns()) {
      recovery.complete(owned.userId);
    }

    await persistence.read();

    return outcome;
  }

  // Mirrors cancelRecovery: the session is ended first, the record goes with the recovery.
  async function cancel() {
    const owned = proofFor();
    let result: "signed-out" | "stale" | "failed";

    try {
      result = await endSession(owned.proof);
    } catch {
      result = "failed";
    }

    if (result === "signed-out") {
      recovery.complete(owned.userId);
    }

    await persistence.read();

    return result;
  }

  return {
    world, server, raw, guarded, queue, boundary, recovery, persistence, handler, puts, counts, published, routeLog, stop, linkFor, proofFor,
    route, updatePassword, endSession, signIn, authorize, holdPut, recoveryRequest, signUpRequest, requests, settled, setPassword, cancel,
    markerRecords: () => [...world.marker.data.values()].map((value) => JSON.parse(value) as { phase: string }),
  };
}

// The process dies (no cleanup of anything durable) and the next one starts on the
// same storage.
function restart(previous: ReturnType<typeof lab>) {
  previous.stop();

  return lab(previous.world);
}

// The device asked for a reset (auth-js stores the PKCE verifier), then the link arrives.
async function openLink(w: ReturnType<typeof lab>, url: string, options: { requested?: boolean } = {}) {
  if (options.requested !== false) {
    await w.recoveryRequest();
  }

  assert.equal(w.handler.receive(url), true);

  return w.handler.drain();
}

describe("recovery on the real auth library", () => {
  it("link -> recovery session -> only the reset route -> new password -> app", async () => {
    const w = lab();

    try {
      await w.settled();
      assert.deepEqual(await openLink(w, w.linkFor("user-a")), { kind: "recovery_ready", userId: "user-a" });
      assert.equal(w.route(), "recovery", "the recovery session is not an app session");

      const owned = w.proofFor();
      const outcome = await updateRecoveredPassword(
        { update: (password) => w.updatePassword(owned.proof, password), isCurrent: () => true },
        "a brand new password",
      );

      assert.deepEqual(outcome, { kind: "updated" });
      assert.equal(w.puts.length, 1);
      assert.equal(w.puts[0].password, "a brand new password");
      w.recovery.complete(owned.userId);
      assert.equal(w.route(), "app");
    } finally {
      w.stop();
    }
  });

  it("a link the server no longer accepts (already used) produces no session", async () => {
    const w = lab();

    try {
      await w.settled();
      assert.deepEqual(await openLink(w, w.linkFor("user-a", { valid: false })), { kind: "link_invalid", reason: "expired_or_used" });
      assert.equal(w.route(), "signed-out");
    } finally {
      w.stop();
    }
  });

  it("opening the same link again is refused locally, not applied twice", async () => {
    const w = lab();

    try {
      await w.settled();

      const link = w.linkFor("user-a");

      await openLink(w, link);
      w.recovery.complete("user-a");
      assert.deepEqual(await openLink(w, link), { kind: "link_invalid", reason: "expired_or_used" });
      assert.equal(w.route(), "app", "the replay did not touch the existing session");
    } finally {
      w.stop();
    }
  });
});

describe("a recovery that belongs to a stale or different session", () => {
  it("user B signs in before the password is set: the update is refused, B's password is untouched", async () => {
    const w = lab();

    try {
      await w.settled();
      await openLink(w, w.linkFor("user-a"));

      const owned = w.proofFor();
      const signedIn = w.signIn("user-b"); // queued first
      const update = updateRecoveredPassword(
        { update: (password) => w.updatePassword(owned.proof, password), isCurrent: () => true },
        "a brand new password",
      );

      await signedIn;
      assert.deepEqual(await update, { kind: "stale" });
      assert.equal(w.puts.length, 0, "no password request was sent for anybody");
      assert.equal(w.boundary.snapshot().userId, "user-b");
      assert.equal(w.recovery.getSnapshot().phase, "idle", "A's recovery does not carry over to B");
      assert.equal(w.route(), "app");
    } finally {
      w.stop();
    }
  });

  it("the update runs first: it carries A's token, and B's sign-in only happens afterwards", async () => {
    const w = lab();

    try {
      await w.settled();
      await openLink(w, w.linkFor("user-a"));

      const owned = w.proofFor();
      const accessOfA = (await w.guarded.getSession()).data.session?.access_token as string;

      w.holdPut.gate = deferred<void>();

      const update = w.updatePassword(owned.proof, "a brand new password");
      const signedIn = w.signIn("user-b");

      await tick(20);
      assert.equal(w.boundary.snapshot().userId, "user-a", "B is still waiting behind the update");
      w.holdPut.gate.resolve();
      assert.deepEqual((await update).status, "done");
      await signedIn;
      assert.equal(w.puts[0].bearer, accessOfA);
      assert.equal(w.boundary.snapshot().userId, "user-b");
    } finally {
      w.stop();
    }
  });

  it("sign-out during a recovery ends it; a later update is refused", async () => {
    const w = lab();

    try {
      await w.settled();
      await openLink(w, w.linkFor("user-a"));

      const owned = w.proofFor();

      assert.equal(await w.endSession(owned.proof), "signed-out");
      assert.equal(w.recovery.getSnapshot().phase, "idle");
      assert.equal(w.route(), "signed-out");
      assert.deepEqual(await w.updatePassword(owned.proof, "x".repeat(10)), { status: "stale" });
      assert.equal(w.puts.length, 0);
    } finally {
      w.stop();
    }
  });

  it("a second recovery link for the same user while the first is active keeps one recovery", async () => {
    const w = lab();

    try {
      await w.settled();
      await openLink(w, w.linkFor("user-a"));
      assert.deepEqual(await openLink(w, w.linkFor("user-a")), { kind: "recovery_ready", userId: "user-a" });
      assert.deepEqual(w.recovery.getSnapshot(), { phase: "active", userId: "user-a" });
    } finally {
      w.stop();
    }
  });
});

describe("cache and user-boundary isolation", () => {
  it("a recovery for a different user than the signed-in one resets the private cache once", async () => {
    const w = lab();

    try {
      await w.settled();
      await w.signIn("user-a");
      assert.equal(w.counts.resets, 0);
      assert.deepEqual(await openLink(w, w.linkFor("user-b")), { kind: "recovery_ready", userId: "user-b" });
      assert.equal(w.counts.resets, 1, "user A's data is retired when B's session arrives");
      assert.equal(w.route(), "recovery");
    } finally {
      w.stop();
    }
  });

  it("a recovery for the same signed-in user keeps the cache", async () => {
    const w = lab();

    try {
      await w.settled();
      await w.signIn("user-a");
      w.authorize((await w.guarded.getSession()).data.session?.access_token as string);
      await openLink(w, w.linkFor("user-a"));
      assert.equal(w.counts.resets, 0);
    } finally {
      w.stop();
    }
  });

  it("leaving a recovery by signing out retires the recovery user's cache", async () => {
    const w = lab();

    try {
      await w.settled();
      await openLink(w, w.linkFor("user-a"));
      await w.endSession(w.proofFor().proof);
      assert.equal(w.counts.resets, 1);
    } finally {
      w.stop();
    }
  });
});

describe("concurrent links and sign-ins", () => {
  it("a sign-in queued behind a link wins; A's recovery does not survive B's session", async () => {
    const w = lab();

    try {
      await w.settled();
      await w.recoveryRequest();
      assert.equal(w.handler.receive(w.linkFor("user-a")), true);

      const link = w.handler.drain();
      const signedIn = w.signIn("user-b");

      // The link's exchange is queued after its (awaited) record write, so B's sign-in
      // may land first and the link then replaces it; either order is legitimate. What
      // must hold is that the FINAL state is consistent: whoever is current, a recovery
      // session is gated and an ordinary session is not.
      assert.ok(["stale", "recovery_ready"].includes((await link)?.kind ?? ""));
      await signedIn;

      const user = w.boundary.snapshot().userId;

      if (user === "user-a") {
        assert.deepEqual(w.recovery.getSnapshot(), { phase: "active", userId: "user-a" });
        assert.equal(w.route(), "recovery");
      } else {
        assert.equal(user, "user-b");
        assert.equal(w.recovery.getSnapshot().phase, "idle", "A's recovery does not survive B's session");
        assert.equal(w.route(), "app");
      }
    } finally {
      w.stop();
    }
  });

  it("two links from one request: the verifier is single-use, so the second fails without releasing the first recovery", async () => {
    const w = lab();

    try {
      await w.settled();
      await w.recoveryRequest();
      w.handler.receive(w.linkFor("user-a"));

      const first = w.handler.drain();

      w.handler.receive(w.linkFor("user-b"));

      const second = w.handler.drain();

      assert.equal((await first)?.kind, "stale", "superseded by the newer attempt");
      assert.deepEqual(await second, { kind: "link_invalid", reason: "expired_or_used" });
      assert.equal(w.boundary.snapshot().userId, "user-a");
      assert.deepEqual(w.recovery.getSnapshot(), { phase: "active", userId: "user-a" });
      assert.equal(w.route(), "recovery", "the stored recovery session is still gated");
    } finally {
      w.stop();
    }
  });
});

describe("only a link for a request made on THIS device can change the session", () => {
  it("login CSRF: a code from somebody else's request never replaces the signed-in user", async () => {
    const w = lab();

    try {
      await w.settled();
      await w.signIn("user-a");
      assert.equal(w.boundary.snapshot().userId, "user-a");

      // The attacker's own account produced this code; this device never asked for it.
      const attackerLink = w.linkFor("attacker");
      const outcome = await openLink(w, attackerLink, { requested: false });

      assert.deepEqual(outcome, { kind: "link_invalid", reason: "expired_or_used" });
      assert.equal(w.boundary.snapshot().userId, "user-a", "still user A");
      assert.equal(w.counts.resets, 0, "A's data was not retired");
      assert.equal(w.requests.exchanges, 0, "auth-js refused before any request: no verifier on this device");
      assert.equal(w.route(), "app");
    } finally {
      w.stop();
    }
  });

  it("a session-carrying link is never applied, whatever it contains", async () => {
    const w = lab();

    try {
      await w.settled();
      await w.signIn("user-a");

      const attackerLink = `valorfinis://auth/callback#access_token=${jwt("attacker")}&refresh_token=attacker-refresh&type=recovery`;

      assert.equal(w.handler.receive(attackerLink), true);
      assert.deepEqual(await w.handler.drain(), { kind: "link_invalid", reason: "unsupported" });
      assert.equal(w.boundary.snapshot().userId, "user-a");
      assert.equal(w.counts.resets, 0);
    } finally {
      w.stop();
    }
  });
});

describe("the purpose of a link as the real library reports it", () => {
  it("a recovery request makes the exchange report 'recovery'", async () => {
    const w = lab();

    try {
      await w.settled();
      await w.recoveryRequest();

      const { data } = await w.guarded.exchangeCodeForSession(new URL(w.linkFor("user-a")).searchParams.get("code") as string);

      assert.equal((data as { redirectType?: unknown }).redirectType, "recovery");
    } finally {
      w.stop();
    }
  });

  it("a sign-up confirmation is a normal session, not a recovery", async () => {
    const w = lab();

    try {
      await w.settled();
      await w.signUpRequest();
      assert.deepEqual(await openLink(w, w.linkFor("user-a"), { requested: false }), { kind: "confirmed" });
      assert.equal(w.recovery.getSnapshot().phase, "idle");
      assert.equal(w.route(), "app");
    } finally {
      w.stop();
    }
  });
});

describe("a failed link never releases a recovery session into the app", () => {
  it("after a recovery link, junk links keep the route on the reset screen", async () => {
    const w = lab();

    try {
      await w.settled();
      await openLink(w, w.linkFor("user-a"));
      assert.equal(w.route(), "recovery");

      for (const url of [
        "valorfinis://auth/callback",
        "valorfinis://auth/callback#error=access_denied&error_code=otp_expired",
        "valorfinis://auth/callback#access_token=a.b.c&refresh_token=r&type=recovery",
        w.linkFor("user-a", { valid: false }),
      ]) {
        assert.equal(w.handler.receive(url), true);
        assert.notEqual(w.route(), "app", `before: ${url.slice(0, 40)}`);
        await w.handler.drain();
        assert.equal(w.route(), "recovery", url.slice(0, 40));
      }
    } finally {
      w.stop();
    }
  });
});

// ---------------------------------------------------------------------------------
// Restart safety: the process is killed and started again on the same storage.
// The recovery session auth-js persisted must never open the protected screens, and
// background financial evaluation (which exists only in the "app" route) stays off.
// ---------------------------------------------------------------------------------
const neverApp = (w: ReturnType<typeof lab>, label: string) =>
  assert.ok(!w.routeLog.includes("app"), `${label}: the app route was reachable (${w.routeLog.join(" > ")})`);
const markerPhases = (w: ReturnType<typeof lab>) => w.markerRecords().map((record) => record.phase);
const hasStoredSession = (w: ReturnType<typeof lab>) => w.world.authStore.has("sb-test-auth-token");

describe("restart: killed on the Reset Password screen", () => {
  it("the persisted recovery session resumes the reset screen, never the app", async () => {
    const first = lab();

    await first.settled();
    assert.deepEqual(await openLink(first, first.linkFor("user-a")), { kind: "recovery_ready", userId: "user-a" });
    assert.equal(first.route(), "recovery");
    await first.persistence.read();
    assert.deepEqual(markerPhases(first), ["active"], "the recovery is recorded durably");
    assert.equal(hasStoredSession(first), true, "auth-js persisted the recovery session");

    const second = restart(first); // killed before the password was changed

    try {
      await second.settled();
      assert.equal(second.boundary.snapshot().userId, "user-a", "the session WAS restored");
      assert.deepEqual(second.recovery.getSnapshot(), { phase: "active", userId: "user-a" });
      assert.equal(second.route(), "recovery");
      neverApp(second, "cold start");
      assert.deepEqual(markerPhases(second), ["active"]);
    } finally {
      second.stop();
    }
  });

  it("the route is closed (loading) from the first instant: never signed-out or app while resolving", async () => {
    const first = lab();

    await first.settled();
    await openLink(first, first.linkFor("user-a"));

    const second = restart(first);

    try {
      await second.settled();
      assert.ok(second.routeLog.length > 0);
      assert.ok(second.routeLog.every((route) => route === "loading" || route === "recovery"), second.routeLog.join(" > "));
    } finally {
      second.stop();
    }
  });

  it("a resumed recovery can still be completed: password update, then restart goes straight to the app", async () => {
    const first = lab();

    await first.settled();
    await openLink(first, first.linkFor("user-a"));

    const second = restart(first);

    await second.settled();
    assert.deepEqual(await second.setPassword("a brand new password"), { kind: "updated" });
    assert.equal(second.route(), "app");
    assert.equal(second.puts.length, 1);
    assert.deepEqual(markerPhases(second), [], "the record is gone with the recovery");

    const third = restart(second);

    try {
      await third.settled();
      assert.equal(third.route(), "app");
      assert.equal(third.boundary.snapshot().userId, "user-a");
      assert.ok(!third.routeLog.includes("recovery"), "no reset screen after the password was set");
      assert.deepEqual(markerPhases(third), []);
    } finally {
      third.stop();
    }
  });

  it("killed between the password change and the record's removal: safe, the reset screen returns", async () => {
    const first = lab();

    await first.settled();
    await openLink(first, first.linkFor("user-a"));
    first.world.marker.faults.remove = true; // the process dies before the record is removed

    await first.setPassword("a brand new password");
    assert.deepEqual(markerPhases(first), ["active"]);
    first.world.marker.faults.remove = false;

    const second = restart(first);

    try {
      await second.settled();
      assert.equal(second.route(), "recovery");
      neverApp(second, "after a lost record removal");
    } finally {
      second.stop();
    }
  });
});

describe("restart: cancel", () => {
  it("cancel, then restart: signed out, nothing stored, the app never reachable", async () => {
    const first = lab();

    await first.settled();
    await openLink(first, first.linkFor("user-a"));
    assert.equal(await first.cancel(), "signed-out");
    assert.equal(hasStoredSession(first), false);
    assert.deepEqual(markerPhases(first), []);

    const second = restart(first);

    try {
      await second.settled();
      assert.equal(second.boundary.snapshot().userId, null);
      assert.equal(second.route(), "signed-out");
      neverApp(second, "after cancel");
    } finally {
      second.stop();
    }
  });

  it("killed between the sign-out and the record's removal: a record without a session is cleared", async () => {
    const first = lab();

    await first.settled();
    await openLink(first, first.linkFor("user-a"));
    first.world.marker.faults.remove = true;
    await first.cancel();
    assert.deepEqual(markerPhases(first), ["active"], "the record outlived the session, never the other way round");
    first.world.marker.faults.remove = false;

    const second = restart(first);

    try {
      await second.settled();
      assert.equal(second.route(), "signed-out");
      assert.deepEqual(markerPhases(second), []);
      neverApp(second, "cancel with a lost record removal");
    } finally {
      second.stop();
    }
  });
});

describe("restart: crash windows around the link exchange", () => {
  it("the record cannot be written: the exchange is not even attempted", async () => {
    const w = lab();

    try {
      await w.settled();
      w.world.marker.faults.write = true;
      assert.deepEqual(await openLink(w, w.linkFor("user-a")), { kind: "unavailable" });
      assert.equal(w.requests.exchanges, 0, "no exchange without a durable record");
      assert.equal(w.boundary.snapshot().userId, null);
      assert.equal(w.recovery.getSnapshot().phase, "idle");
      neverApp(w, "unwritable record");
    } finally {
      w.stop();
    }
  });

  it("killed after the session was stored but before the 'active' record: failing closed, signed out", async () => {
    const first = lab();

    await first.settled();
    first.world.marker.faults.failSet = (value) => (JSON.parse(value) as { phase: string }).phase === "active";
    assert.deepEqual(await openLink(first, first.linkFor("user-a")), { kind: "recovery_ready", userId: "user-a" });
    await first.persistence.read();
    assert.deepEqual(markerPhases(first), ["verifying"], "only the pre-exchange record is durable");
    assert.equal(hasStoredSession(first), true);
    first.world.marker.faults.failSet = null;

    const second = restart(first);

    try {
      await second.settled();
      assert.equal(second.boundary.snapshot().userId, null, "the unexplained session was ended");
      assert.equal(hasStoredSession(second), false);
      assert.equal(second.route(), "signed-out");
      assert.deepEqual(markerPhases(second), []);
      neverApp(second, "crash between exchange and record");
    } finally {
      second.stop();
    }
  });

  it("killed during the exchange with no session stored: the leftover record is just cleared", async () => {
    const first = lab();

    await first.settled();
    await first.persistence.writeVerifying({ priorUserId: null, recoveryUserId: null });

    const second = restart(first);

    try {
      await second.settled();
      assert.equal(second.route(), "signed-out");
      assert.deepEqual(markerPhases(second), []);
    } finally {
      second.stop();
    }
  });

  it("killed during an exchange that did not replace the signed-in user's ordinary session: that user is kept", async () => {
    const first = lab();

    await first.settled();
    await first.signIn("user-a");
    await first.persistence.writeVerifying({ priorUserId: "user-a", recoveryUserId: null });

    const second = restart(first);

    try {
      await second.settled();
      assert.equal(second.boundary.snapshot().userId, "user-a");
      assert.equal(second.route(), "app");
      assert.deepEqual(markerPhases(second), []);
    } finally {
      second.stop();
    }
  });

  it("an unreadable record with a session fails closed", async () => {
    const first = lab();

    await first.settled();
    await first.signIn("user-a");
    first.world.marker.data.set("valorfinis.password-recovery.v1", "{corrupt");

    const second = restart(first);

    try {
      await second.settled();
      assert.equal(second.boundary.snapshot().userId, null);
      assert.equal(second.route(), "signed-out");
      neverApp(second, "corrupt record");
    } finally {
      second.stop();
    }
  });
});

describe("restart: a recovery that belongs to somebody else", () => {
  it("user B signed in after the recovery and the process died before the record was removed: B is a normal user", async () => {
    const first = lab();

    await first.settled();
    await openLink(first, first.linkFor("user-a"));
    first.world.marker.faults.remove = true; // the reconcile-driven removal is lost
    await first.signIn("user-b");
    await first.persistence.read();
    assert.deepEqual(markerPhases(first), ["active"], "a stale record for A is still on disk");
    first.world.marker.faults.remove = false;

    const second = restart(first);

    try {
      await second.settled();
      assert.equal(second.boundary.snapshot().userId, "user-b");
      assert.equal(second.route(), "app");
      assert.ok(!second.routeLog.includes("recovery"), "B is never sent to A's reset screen");
      assert.deepEqual(markerPhases(second), []);
    } finally {
      second.stop();
    }
  });

  it("an active record with nobody signed in is dropped; a later ordinary sign-in is not gated", async () => {
    const first = lab();

    await first.settled();
    await first.persistence.writeActive("user-a");

    const second = restart(first);

    try {
      await second.settled();
      assert.equal(second.route(), "signed-out");
      await second.signIn("user-a");
      assert.equal(second.route(), "app", "user A's ordinary sign-in is not mistaken for a recovery");
    } finally {
      second.stop();
    }
  });
});

describe("restart: stale, replayed and expired links", () => {
  it("replaying the used link after a restart fails (no verifier, code spent) and the recovery stays in force", async () => {
    const first = lab();

    await first.settled();

    const link = first.linkFor("user-a");

    await openLink(first, link);

    const second = restart(first);

    try {
      await second.settled();
      assert.equal(second.handler.receive(link), true, "this process has no memory of the first one");
      assert.deepEqual(await second.handler.drain(), { kind: "link_invalid", reason: "expired_or_used" });
      assert.deepEqual(second.recovery.getSnapshot(), { phase: "active", userId: "user-a" });
      await second.persistence.read();
      assert.deepEqual(markerPhases(second), ["active"], "the record is back to 'active' after the failed attempt");
      neverApp(second, "replay after restart");
    } finally {
      second.stop();
    }
  });

  it("an expired link after a restart: invalid, the recovery stays in force", async () => {
    const first = lab();

    await first.settled();
    await openLink(first, first.linkFor("user-a"));

    const second = restart(first);

    try {
      await second.settled();
      await second.recoveryRequest();
      assert.equal(second.handler.receive(second.linkFor("user-a", { valid: false })), true);
      assert.deepEqual(await second.handler.drain(), { kind: "link_invalid", reason: "expired_or_used" });
      assert.equal(second.route(), "recovery");
      neverApp(second, "expired link after restart");
    } finally {
      second.stop();
    }
  });

  it("a malformed or error link during the resumed recovery changes nothing", async () => {
    const first = lab();

    await first.settled();
    await openLink(first, first.linkFor("user-a"));

    const second = restart(first);

    try {
      await second.settled();

      for (const url of ["valorfinis://auth/callback", "valorfinis://auth/callback#error=access_denied&error_code=otp_expired"]) {
        second.handler.receive(url);
        await second.handler.drain();
        assert.equal(second.route(), "recovery", url);
      }

      neverApp(second, "junk links after restart");
    } finally {
      second.stop();
    }
  });

  it("a link that opens the app (cold start) while the previous recovery is still being resolved waits, then takes over", async () => {
    const first = lab();

    await first.settled();
    await openLink(first, first.linkFor("user-a"));
    await first.recoveryRequest(); // a second request: a new verifier

    const newLink = first.linkFor("user-a");
    const second = restart(first);

    try {
      assert.equal(second.handler.receive(newLink), true, "handed over by the OS before authentication is up");
      assert.equal(second.recovery.getSnapshot().phase, "resolving");
      await second.settled();
      assert.equal(second.recovery.getSnapshot().phase, "verifying", "the link now owns the gate");
      assert.deepEqual(await second.handler.drain(), { kind: "recovery_ready", userId: "user-a" });
      assert.equal(second.route(), "recovery");
      neverApp(second, "cold-start link");
    } finally {
      second.stop();
    }
  });
});

describe("restart: background financial evaluation stays disabled throughout", () => {
  it("evaluation exists only in the 'app' route, and no recovery path ever reaches it", async () => {
    const first = lab();

    await first.settled();
    await openLink(first, first.linkFor("user-a"));
    neverApp(first, "first process");

    const second = restart(first);

    try {
      await second.settled();
      await second.setPassword("a brand new password");

      // Only after the password is set does the same session become an app session.
      assert.equal(second.route(), "app");

      const firstApp = second.routeLog.indexOf("app");
      const lastRecovery = second.routeLog.lastIndexOf("recovery");

      assert.ok(lastRecovery !== -1 && firstApp > lastRecovery, second.routeLog.join(" > "));
    } finally {
      second.stop();
    }
  });
});

describe("restart while the stored session cannot be read (restore failure)", () => {
  // The late session arrives the way auth-js delivers one after a failed restore: as an
  // auth event (here from a refresh once the storage answers again).
  async function sessionArrivesLate(w: ReturnType<typeof lab>) {
    w.world.storeFail.on = false;

    const { error } = await w.guarded.refreshSession();

    assert.equal(error, null);
    await w.settled();
  }

  it("the app stays closed, keeps the record, and gates the session when it finally loads", async () => {
    const first = lab();

    await first.settled();
    await openLink(first, first.linkFor("user-a"));
    first.world.storeFail.on = true;

    const second = restart(first);

    try {
      await second.settled();
      assert.equal(second.boundary.snapshot().userId, null, "the session could not be restored");
      assert.equal(second.route(), "signed-out");
      assert.deepEqual(markerPhases(second), ["active"], "the record is NOT cleared by a failed restore");

      await sessionArrivesLate(second);
      assert.equal(second.boundary.snapshot().userId, "user-a");
      assert.equal(second.route(), "recovery", "the late session is a recovery session, not an app session");
      neverApp(second, "failed restore then late session");
    } finally {
      second.stop();
    }
  });

  it("an unexplained session that loads late is ended, not opened", async () => {
    const first = lab();

    await first.settled();
    first.world.marker.faults.failSet = (value) => (JSON.parse(value) as { phase: string }).phase === "active";
    await openLink(first, first.linkFor("user-a"));
    first.world.marker.faults.failSet = null;
    assert.deepEqual(markerPhases(first), ["verifying"]);
    first.world.storeFail.on = true;

    const second = restart(first);

    try {
      await second.settled();
      assert.equal(second.route(), "signed-out");
      await sessionArrivesLate(second);
      assert.equal(second.boundary.snapshot().userId, null, "the unexplained session was ended");
      assert.equal(second.route(), "signed-out");
      assert.deepEqual(markerPhases(second), []);
      neverApp(second, "failed restore then unexplained late session");
    } finally {
      second.stop();
    }
  });

  it("a link that fails while the recovery is deferred does NOT erase it: the late session is still a recovery session", async () => {
    const first = lab();

    await first.settled();
    await openLink(first, first.linkFor("user-a"));
    first.world.storeFail.on = true;

    const second = restart(first);

    try {
      await second.settled();
      assert.equal(second.route(), "signed-out");

      // An old / expired link is tapped while the stored session still cannot be read.
      assert.deepEqual(await openLink(second, second.linkFor("user-a", { valid: false })), { kind: "link_invalid", reason: "expired_or_used" });
      // auth-js may deliver the stored session as its own initial event while the link
      // runs (timing); either way the recovery must never be released: deferred (still
      // unjudged) or already judged and active, never idle.
      assert.ok(["deferred", "active"].includes(second.recovery.getSnapshot().phase), second.recovery.getSnapshot().phase);
      await second.persistence.read();
      assert.deepEqual(second.world.marker.data.size, 1, "a record is still on disk");

      await sessionArrivesLate(second);
      assert.equal(second.boundary.snapshot().userId, "user-a");
      assert.equal(second.route(), "recovery");
      neverApp(second, "failed link while deferred, then late session");
    } finally {
      second.stop();
    }
  });

  it("a failed restore with NO recorded recovery defers nothing: the ordinary session reaches the app", async () => {
    const first = lab();

    await first.settled();
    await first.signIn("user-a");
    first.world.refreshOwners.set((JSON.parse(first.world.authStore.get("sb-test-auth-token") as string) as { refresh_token: string }).refresh_token, "user-a");
    first.world.storeFail.on = true;

    const second = restart(first);

    try {
      await second.settled();
      assert.equal(second.route(), "signed-out");
      await sessionArrivesLate(second);
      assert.equal(second.route(), "app");
    } finally {
      second.stop();
    }
  });
});

describe("a sign-out that did not happen is never reported as done", () => {
  it("Cancel while the session cannot be ended: it fails, the recovery and its record stay in force", async () => {
    const first = lab();

    await first.settled();
    await openLink(first, first.linkFor("user-a"));
    first.world.signOutFails.on = true; // expired stored session, auth server unreachable

    assert.equal(await first.cancel(), "failed");
    assert.equal(first.boundary.snapshot().userId, "user-a", "the session is still there");
    assert.deepEqual(first.recovery.getSnapshot(), { phase: "active", userId: "user-a" });
    assert.equal(first.route(), "recovery", "so the reset screen stays");
    assert.deepEqual(markerPhases(first), ["active"], "and so does its record");
    neverApp(first, "failed cancel");

    const second = restart(first);

    try {
      await second.settled();
      assert.equal(second.route(), "recovery", "after a restart too");
      neverApp(second, "restart after a failed cancel");

      // Once the sign-out works, Cancel completes normally.
      second.world.signOutFails.on = false;
      assert.equal(await second.cancel(), "signed-out");
      assert.equal(second.route(), "signed-out");
      assert.deepEqual(markerPhases(second), []);
    } finally {
      second.stop();
    }
  });

  it("startup cannot end an unexplained session: the reset screen, never the app", async () => {
    const first = lab();

    await first.settled();
    first.world.marker.faults.failSet = (value) => (JSON.parse(value) as { phase: string }).phase === "active";
    await openLink(first, first.linkFor("user-a"));
    first.world.marker.faults.failSet = null;
    first.world.signOutFails.on = true;

    const second = restart(first);

    try {
      await second.settled();
      assert.equal(second.boundary.snapshot().userId, "user-a");
      assert.equal(second.route(), "recovery");
      neverApp(second, "startup sign-out failure");
      await second.persistence.read();
      assert.deepEqual(markerPhases(second), ["active"]);
    } finally {
      second.stop();
    }
  });
});
