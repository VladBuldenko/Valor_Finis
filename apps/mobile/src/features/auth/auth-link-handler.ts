// Turns an incoming auth link into a Supabase session, safely. Pure and
// dependency-injected (no React Native / Supabase import) so every race is tested.
//
// ONLY PKCE LINKS (`?code=`) ARE ACCEPTED. A link that carries the session itself
// (`#access_token=..&refresh_token=..`) or a one-time token hash is not bound to the
// device that asked for it, so anybody could send a victim a link made from the
// attacker's own account and silently switch the victim's app to it (login CSRF).
// A PKCE code is useless without the code verifier the requesting device stored, so
// only a link for a request made on THIS device can be exchanged. The parser still
// recognizes the other forms so they are refused with a clear outcome instead of
// being mistaken for something else.
//
// Flow: `receive(url)` is called synchronously the moment the OS hands the URL to
// the app (cold start or already running). It claims links that belong to this
// module. Only a link that WILL change the session (a fresh PKCE code) marks the
// recovery state "verifying" (a neutral loading UI); a malformed, expired, refused or
// replayed link changes no state at all, so it can never release a recovery
// session into the app. `drain()` is called once authentication is initialized and
// does the asynchronous work.
//
// Guarantees
//  * ONE attempt per link: the same URL delivered twice (initial URL plus the url
//    event) is processed once; opening a link again after it was used reports
//    "invalid or expired" WITHOUT calling the server again. A link whose attempt
//    could not reach the server (offline) is NOT marked used: opening it again retries.
//  * Newest link wins: every attempt has a generation (recovery-state); an older
//    attempt that resolves late applies nothing and shows nothing. If it produced a
//    recovery session that is still the current session, that session stays gated.
//  * Identity check: after the session is established, the recovery is activated
//    only if the authoritative current user is still the user of that session.
//  * The exchange goes through the app's guarded Supabase client, i.e. the auth
//    operation queue, like every other session change.
//  * Nothing is retried automatically, and no credential, URL, token or server
//    message is logged or placed in an outcome.
import { classifyAuthFailure } from "./auth-errors.ts";
import { parseAuthLink, type ParseOptions } from "./auth-link.ts";
import type { RecoveryState } from "./recovery-state.ts";

type SessionResult = {
  data: { session: { user: { id: string } } | null; redirectType?: string | null } | null;
  error: unknown;
};

export type LinkAuth = {
  exchangeCodeForSession: (code: string) => Promise<SessionResult>;
};

// auth-js reports the purpose of a PKCE exchange as the suffix stored with the
// verifier: "recovery" (verified against auth-js 2.112.3). "PASSWORD_RECOVERY" is the
// name of the corresponding auth event and is accepted too.
function isRecoveryRedirect(redirectType: unknown): boolean {
  return redirectType === "recovery" || redirectType === "PASSWORD_RECOVERY";
}

export type LinkOutcome =
  // A recovery session for `userId` is active: show the reset screen.
  | { kind: "recovery_ready"; userId: string }
  // A confirmation link produced a (normal) session.
  | { kind: "confirmed" }
  // Expired, already used, malformed, unsupported or not for this device.
  | { kind: "link_invalid"; reason: "expired_or_used" | "malformed" | "unsupported" }
  // The auth server could not be reached; the link was not consumed.
  | { kind: "unavailable" }
  // Superseded by a newer link, or the signed-in user changed: nothing was applied.
  | { kind: "stale" };

export type LinkNotice = { id: number; outcome: LinkOutcome };

export type AuthLinkHandlerDeps = {
  parse: ParseOptions;
  auth: LinkAuth;
  // The authoritative current user (from the session boundary). Synchronous.
  currentUserId: () => string | null;
  recovery: RecoveryState;
};

type Job = {
  parsed: ReturnType<typeof parseAuthLink>;
  fingerprint: string;
  // The recovery-state generation; null for a link that cannot change the session.
  attempt: number | null;
  replay: boolean;
};

// FNV-1a over the string: a fixed-size fingerprint so the app never keeps the URL
// (which holds a credential) to recognize a repeat. Not a security primitive.
function fingerprintOf(url: string): string {
  let h1 = 0x811c9dc5;
  let h2 = 0x01000193;

  for (let index = 0; index < url.length; index += 1) {
    const code = url.charCodeAt(index);

    h1 = Math.imul(h1 ^ code, 0x01000193) >>> 0;
    h2 = Math.imul(h2 + code, 0x85ebca6b) >>> 0;
  }

  return `${url.length}:${h1.toString(16)}:${h2.toString(16)}`;
}

export function createAuthLinkHandler(deps: AuthLinkHandlerDeps) {
  let pending: Job | null = null;
  let noticeId = 0;
  let notice: LinkNotice | null = null;
  const seen = new Map<string, "inflight" | "done">();
  const pendingListeners = new Set<() => void>();
  const noticeListeners = new Set<() => void>();

  function publish(outcome: LinkOutcome): void {
    if (outcome.kind === "stale") {
      return;
    }

    noticeId += 1;
    notice = { id: noticeId, outcome };
    noticeListeners.forEach((listener) => listener());
  }

  async function establish(job: Job, code: string): Promise<LinkOutcome> {
    const attempt = job.attempt as number;
    const result = await deps.auth.exchangeCodeForSession(code);

    if (result.error) {
      return classifyAuthFailure(result.error) === "network"
        ? { kind: "unavailable" }
        : { kind: "link_invalid", reason: "expired_or_used" };
    }

    const user = result.data?.session?.user;

    if (!user) {
      return { kind: "link_invalid", reason: "expired_or_used" };
    }

    const recovery = isRecoveryRedirect(result.data?.redirectType);

    // Somebody else is the current user now: nothing of this link applies.
    if (deps.currentUserId() !== user.id) {
      return { kind: "stale" };
    }

    // Superseded by a newer link. If this was a recovery session and it is the
    // current session, it must stay gated even though its attempt was replaced.
    if (!deps.recovery.isCurrent(attempt)) {
      if (recovery) {
        deps.recovery.keepRecovery(user.id);
      }

      return { kind: "stale" };
    }

    if (recovery) {
      return deps.recovery.activate(attempt, user.id)
        ? { kind: "recovery_ready", userId: user.id }
        : { kind: "stale" };
    }

    return { kind: "confirmed" };
  }

  async function run(job: Job): Promise<LinkOutcome> {
    const { parsed } = job;

    if (job.replay) {
      return { kind: "link_invalid", reason: "expired_or_used" };
    }

    switch (parsed.kind) {
      case "code":
        return establish(job, parsed.code);
      case "failed_link":
        return { kind: "link_invalid", reason: "expired_or_used" };
      case "session_tokens":
      case "token_hash":
        // Not bound to this device (see the header): never turned into a session.
        return { kind: "link_invalid", reason: "unsupported" };
      default:
        return { kind: "link_invalid", reason: "malformed" };
    }
  }

  return {
    // Synchronous. True when the URL belongs to this module (the caller then must
    // not route it anywhere else).
    receive(url: unknown): boolean {
      const parsed = parseAuthLink(url, deps.parse);

      if (parsed.kind === "ignore" || typeof url !== "string") {
        return false;
      }

      const fingerprint = fingerprintOf(url);
      const state = seen.get(fingerprint);

      // The same link delivered twice while the first is still being handled.
      if (state === "inflight") {
        return true;
      }

      // An older link that was never started is replaced; it was not used, so
      // opening it again later must work.
      if (pending && !pending.replay) {
        seen.delete(pending.fingerprint);
      }

      // Its attempt will never run: release the gate it closed.
      if (pending && pending.attempt !== null) {
        deps.recovery.finish(pending.attempt);
      }

      if (state === undefined) {
        seen.set(fingerprint, "inflight");
      }

      const replay = state === "done";

      // Only a link that will change the session closes the gate and starts an attempt.
      pending = { parsed, fingerprint, attempt: parsed.kind === "code" && !replay ? deps.recovery.begin() : null, replay };
      pendingListeners.forEach((listener) => listener());

      return true;
    },

    // Runs the pending link, if any. Never throws.
    async drain(): Promise<LinkOutcome | null> {
      const job = pending;

      if (!job) {
        return null;
      }

      pending = null;

      let outcome: LinkOutcome;

      try {
        outcome = await run(job);
      } catch {
        // An unexpected failure is "did not reach a decision", never a guess.
        outcome = { kind: "unavailable" };
      }

      if (job.attempt !== null && outcome.kind !== "recovery_ready") {
        deps.recovery.finish(job.attempt);
      }

      if (outcome.kind === "unavailable") {
        seen.delete(job.fingerprint);
      } else if (!job.replay) {
        seen.set(job.fingerprint, "done");
      }

      publish(outcome);

      return outcome;
    },

    hasPending: (): boolean => pending !== null,

    subscribePending(listener: () => void): () => void {
      pendingListeners.add(listener);

      return () => {
        pendingListeners.delete(listener);
      };
    },

    // The latest outcome for the UI to show once (acknowledged by id).
    getNotice: (): LinkNotice | null => notice,

    acknowledge(id: number): void {
      if (notice?.id === id) {
        notice = null;
        noticeListeners.forEach((listener) => listener());
      }
    },

    subscribeNotice(listener: () => void): () => void {
      noticeListeners.add(listener);

      return () => {
        noticeListeners.delete(listener);
      };
    },
  };
}

export type AuthLinkHandler = ReturnType<typeof createAuthLinkHandler>;
