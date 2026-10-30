// Makes "every call that can change WHICH session is stored goes through the app's
// auth operation queue" a property of the exported client instead of a
// convention (MF2-SR09).
//
// Why it matters, verified against @supabase/auth-js 2.112.3: signInWithPassword
// and the other sign-in methods do NOT take the client's lock, while signOut
// reads the stored session, makes a network call and then removes whatever is
// stored at that moment. A sign-in that completes in between is erased locally
// (and the sign-out's server call revoked the older session). The guarded
// sign-out in auth-operations.ts is atomic with respect to everything on the
// queue; this proxy puts every session-changing call there.
//
// What it cannot and does not queue: the library's own background work
// (auto-refresh tick, foreground recovery, initialization). Those only ever act on the
// session that is already stored: they can move it to a newer token of the same
// user (TOKEN_REFRESHED) or end it (SIGNED_OUT), never establish a different
// user, so they cannot make a sign-out hit someone else (see the integration
// tests).
import type { AuthOperationQueue } from "./auth-operations.ts";

// Calls that can store a session of a (possibly different) user, or end one.
export const SESSION_MUTATORS: ReadonlySet<string> = new Set([
  "signInAnonymously",
  "signUp",
  "signInWithPassword",
  "signInWithOAuth",
  "exchangeCodeForSession",
  "signInWithWeb3",
  "signInWithEthereum",
  "signInWithSolana",
  "signInWithIdToken",
  "signInWithSSO",
  "signInWithPasskey",
  "verifyOtp",
  "setSession",
  "refreshSession",
  "signOut",
]);

// Public methods that do not establish a different user's session. A public
// method of the installed auth-js that is in neither list fails a test, so an
// upgrade that adds a session-changing call cannot slip through unclassified.
export const SESSION_PASSTHROUGH: ReadonlySet<string> = new Set([
  "jwks",
  "jwks_cached_at",
  "isThrowOnErrorEnabled",
  "initialize",
  "signInWithOtp", // sends a code; the session comes from verifyOtp
  "reauthenticate",
  "resend",
  "getSession", // may refresh or drop an invalid stored session of the SAME user
  "getUser",
  "updateUser", // same user
  "onAuthStateChange",
  "resetPasswordForEmail",
  "getUserIdentities",
  "linkIdentity",
  "linkIdentityOAuth",
  "linkIdentityIdToken",
  "unlinkIdentity",
  "startAutoRefresh",
  "stopAutoRefresh",
  "dispose",
  "fetchJwk",
  "getClaims",
  "registerPasskey",
]);

export function queueSessionMutations<T extends object>(auth: T, queue: AuthOperationQueue): T {
  return new Proxy(auth, {
    get(target, property) {
      const value: unknown = Reflect.get(target, property, target);

      if (typeof value !== "function") {
        return value;
      }

      const method = value as (...args: unknown[]) => unknown;

      if (typeof property === "string" && SESSION_MUTATORS.has(property)) {
        return (...args: unknown[]) =>
          queue.run(async () => method.apply(target, args));
      }

      return method.bind(target);
    },
  });
}
