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
} from "../../api/auth-operations.ts";
import { createFakeGoTrueServer, deferred, tick } from "../../api/auth-js-test-support.ts";
import { SessionBoundary } from "../../api/session-boundary.ts";
import type { OwnershipProof } from "../../api/session-lifecycle.ts";
import { createAuthLinkHandler, type LinkAuth } from "./auth-link-handler.ts";
import { startAuthSession, type AuthClientLike } from "./auth-session.ts";
import { updateRecoveredPassword } from "./password-recovery.ts";
import { createRecoveryState, decideRootRoute } from "./recovery-state.ts";

const b64 = (value: unknown) => Buffer.from(JSON.stringify(value)).toString("base64url");
let serial = 0;

function jwt(sub: string, expiresInSeconds = 3600): string {
  serial += 1;

  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub, role: "authenticated", serial, exp: Math.floor(Date.now() / 1000) + expiresInSeconds })}.sig`;
}

const userJson = (id: string) => ({ id, aud: "authenticated", email: `${id}@example.test`, app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" });
const json = (status: number, body: unknown) =>
  new Response(body === null ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function lab() {
  const server = createFakeGoTrueServer();
  const puts: { bearer: string; password: string }[] = [];
  const validAccess = new Set<string>();
  // PKCE codes the scripted server will exchange: code -> user id.
  const codes = new Map<string, string>();
  const requests = { recover: 0, signUp: 0, exchanges: 0 };
  const holdPut = { gate: null as ReturnType<typeof deferred<void>> | null };
  const fetchImpl = async (input: unknown, init: RequestInit = {}): Promise<Response> => {
    const url = new URL(String(input));

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

      const body = JSON.parse(String(init.body)) as { auth_code: string; code_verifier: string };
      const userId = codes.get(body.auth_code);

      if (!userId || !body.code_verifier) {
        return json(404, { code: "flow_state_not_found", message: "flow state not found" });
      }

      codes.delete(body.auth_code); // a code works once
      serial += 1;

      const access = jwt(userId);

      validAccess.add(access);

      return json(200, { access_token: access, token_type: "bearer", expires_in: 3600, refresh_token: `pkce-refresh-${userId}-${serial}`, user: userJson(userId) });
    }

    return server.fetch(input as string, init);
  };

  const store = new Map<string, string>();
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
  const recovery = createRecoveryState();
  const published: (Session | null)[] = [];
  const stop = startAuthSession<Session>({
    auth: guarded as unknown as AuthClientLike<Session>,
    boundary,
    publish: ({ session }) => {
      recovery.reconcile(session?.user.id ?? null);
      published.push(session);
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
  });
  const updatePassword = createGuardedPasswordUpdate({
    queue,
    update: (password) => guarded.updateUser({ password }),
  });
  const endSession = createGuardedSessionEnd({ queue, signOutLocal: async () => { await raw.signOut({ scope: "local" }); } });

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

  const route = () => decideRootRoute({ isLoading: false, userId: boundary.snapshot().userId, recovery: recovery.getSnapshot() });
  const signIn = (id: string) => guarded.signInWithPassword({ email: `${id}@example.test`, password: "pw" });
  const authorize = (access: string) => validAccess.add(access);

  return { server, raw, guarded, queue, boundary, recovery, handler, puts, counts, published, stop, linkFor, proofFor, route, updatePassword, endSession, signIn, authorize, holdPut, recoveryRequest, signUpRequest, requests };
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
      await tick();
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
      await tick();
      assert.deepEqual(await openLink(w, w.linkFor("user-a", { valid: false })), { kind: "link_invalid", reason: "expired_or_used" });
      assert.equal(w.route(), "signed-out");
    } finally {
      w.stop();
    }
  });

  it("opening the same link again is refused locally, not applied twice", async () => {
    const w = lab();

    try {
      await tick();

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
      await tick();
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
      await tick();
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
      await tick();
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
      await tick();
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
      await tick();
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
      await tick();
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
      await tick();
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
      await tick();
      await w.recoveryRequest();
      assert.equal(w.handler.receive(w.linkFor("user-a")), true);

      const link = w.handler.drain();
      const signedIn = w.signIn("user-b");

      // Whether the link's own continuation or B's sign-in runs first is a
      // scheduling detail; what must hold is the FINAL state below.
      assert.ok(["stale", "recovery_ready"].includes((await link)?.kind ?? ""));
      await signedIn;
      assert.equal(w.boundary.snapshot().userId, "user-b");
      assert.equal(w.recovery.getSnapshot().phase, "idle");
      assert.equal(w.route(), "app");
    } finally {
      w.stop();
    }
  });

  it("two links from one request: the verifier is single-use, so the second fails without releasing the first recovery", async () => {
    const w = lab();

    try {
      await tick();
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
      await tick();
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
      await tick();
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
      await tick();
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
      await tick();
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
      await tick();
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
