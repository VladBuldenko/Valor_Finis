// A REAL @supabase/auth-js GoTrueClient (the exact installed version, with the
// same `processLock` the app uses and an in-memory storage) talking to a scripted
// GoTrue server through auth-js's own `fetch` option. Nothing in the library is
// mocked: sessions, locks, events, refresh single-flighting and signOut run as
// shipped. Not imported by app code.
import { GoTrueClient, processLock } from "@supabase/supabase-js";

export type Deferred<T> = { promise: Promise<T>; resolve: (value: T) => void };

export function deferred<T>(): Deferred<T> {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((done) => { resolve = done; });

  return { promise, resolve };
}

function base64url(value: unknown): string {
  return Buffer.from(JSON.stringify(value)).toString("base64url");
}

function jwt(sub: string, serial: number): string {
  const exp = Math.floor(Date.now() / 1000) + 3600;

  return `${base64url({ alg: "HS256", typ: "JWT" })}.${base64url({ sub, exp, role: "authenticated", serial })}.sig`;
}

export type FakeServer = ReturnType<typeof createFakeGoTrueServer>;

export function createFakeGoTrueServer() {
  let serial = 0;
  const refreshTokens = new Map<string, string>(); // refresh token -> user id
  const gates = {
    // Holds the response of a request until the test releases it.
    password: new Map<string, Deferred<void>>(), // by email
    logout: null as Deferred<void> | null,
    refresh: null as Deferred<void> | null,
  };
  const log = {
    logouts: [] as string[], // access tokens revoked server-side
    refreshRequests: 0,
    passwordRequests: [] as string[],
  };
  const behavior = { rejectRefresh: false, hangLogout: false };

  function issue(userId: string) {
    serial += 1;

    const refresh = `refresh-${userId}-${serial}`;

    refreshTokens.set(refresh, userId);

    return {
      access_token: jwt(userId, serial),
      token_type: "bearer",
      expires_in: 3600,
      refresh_token: refresh,
      user: { id: userId, aud: "authenticated", email: `${userId}@example.test`, app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" },
    };
  }

  const reply = (status: number, body: unknown) =>
    new Response(body === null ? null : JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });

  const fetchImpl = async (input: unknown, init: RequestInit = {}): Promise<Response> => {
    const url = new URL(String(input));
    const body = init.body ? (JSON.parse(String(init.body)) as Record<string, string>) : {};

    if (url.pathname.endsWith("/token") && url.searchParams.get("grant_type") === "password") {
      log.passwordRequests.push(body.email);
      await gates.password.get(body.email)?.promise;

      return reply(200, issue(body.email.replace("@example.test", "")));
    }

    if (url.pathname.endsWith("/token") && url.searchParams.get("grant_type") === "refresh_token") {
      log.refreshRequests += 1;
      await gates.refresh?.promise;

      const userId = refreshTokens.get(body.refresh_token);

      if (behavior.rejectRefresh || !userId) {
        return reply(400, { code: "refresh_token_not_found", message: "Invalid Refresh Token: Refresh Token Not Found" });
      }

      refreshTokens.delete(body.refresh_token);

      return reply(200, issue(userId));
    }

    if (url.pathname.endsWith("/logout")) {
      const header = new Headers(init.headers).get("Authorization") ?? "";

      if (behavior.hangLogout) {
        // Never answers unless the caller aborts (fetch-with-timeout does).
        await new Promise((_resolve, reject) => {
          init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
        });
      }

      await gates.logout?.promise;
      log.logouts.push(header.replace("Bearer ", ""));

      return reply(204, null);
    }

    return reply(404, { message: "not found" });
  };

  return { fetch: fetchImpl as typeof fetch, gates, log, behavior };
}

export function createRealAuth(server: FakeServer, options: { fetch?: typeof fetch; autoRefreshToken?: boolean } = {}) {
  const store = new Map<string, string>();
  const storage = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => { store.set(key, value); },
    removeItem: (key: string) => { store.delete(key); },
  };
  const client = new GoTrueClient({
    url: "https://auth.test",
    headers: { apikey: "test-publishable-key" },
    storageKey: "sb-test-auth-token",
    storage,
    persistSession: true,
    autoRefreshToken: options.autoRefreshToken ?? false,
    detectSessionInUrl: false,
    lock: processLock,
    fetch: options.fetch ?? server.fetch,
  });

  return { client, store };
}

export const tick = (ms = 5) => new Promise((resolve) => setTimeout(resolve, ms));
