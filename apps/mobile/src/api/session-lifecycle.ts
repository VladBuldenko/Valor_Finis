// Decides what a HTTP 401 means for the session. Pure and dependency-injected
// (no Supabase / React Native import) so the concurrency rules are testable.
//
// Rules:
//  * A 401 only matters if the token that failed is still the ACTIVE
//    session's token. An old request that was rejected after the session was
//    refreshed, replaced or ended must never end the newer session.
//  * Simultaneous 401s for the same token share ONE check.
//  * The session is ended only when it is CONFIRMED invalid, i.e. the
//    authentication server itself rejects the refresh. If the server cannot be
//    reached the session is kept (a flaky network is not a logout).
//  * Nothing here replays a request.

export type SessionIdentity = {
  userId: string;
  accessToken: string;
};

export type RefreshResult =
  | { status: "refreshed"; session: SessionIdentity }
  // The auth server rejected the refresh (revoked, expired, unknown session).
  | { status: "rejected" }
  // The auth server could not be reached or failed (network, 5xx, 429).
  | { status: "unavailable" };

export type UnauthorizedOutcome =
  | "stale"
  | "refreshed"
  | "signed-out"
  | "unconfirmed";

export type SessionLifecycleDeps = {
  getCurrentSession: () => Promise<SessionIdentity | null>;
  refreshSession: () => Promise<RefreshResult>;
  // Ends the local session and the private data tied to it.
  endSession: () => Promise<void>;
};

export type SessionLifecycle = {
  handleUnauthorized: (used: SessionIdentity) => Promise<UnauthorizedOutcome>;
};

function sameSession(a: SessionIdentity | null, b: SessionIdentity): boolean {
  return a !== null && a.userId === b.userId && a.accessToken === b.accessToken;
}

export function createSessionLifecycle(deps: SessionLifecycleDeps): SessionLifecycle {
  const inFlight = new Map<string, Promise<UnauthorizedOutcome>>();

  async function check(used: SessionIdentity): Promise<UnauthorizedOutcome> {
    if (!sameSession(await deps.getCurrentSession(), used)) {
      return "stale";
    }

    const refreshed = await deps.refreshSession();

    if (refreshed.status === "unavailable") {
      return "unconfirmed";
    }

    if (refreshed.status === "refreshed") {
      // A new token means the session itself is alive. The same token coming
      // back proves nothing, so it is not treated as a recovery.
      return refreshed.session.accessToken === used.accessToken ? "unconfirmed" : "refreshed";
    }

    // Re-check after the await: other work may have replaced or
    // ended the session while the refresh was running.
    if (!sameSession(await deps.getCurrentSession(), used)) {
      return "stale";
    }

    await deps.endSession();

    return "signed-out";
  }

  return {
    handleUnauthorized(used) {
      const key = `${used.userId}:${used.accessToken}`;
      const pending = inFlight.get(key);

      if (pending) {
        return pending;
      }

      const started = check(used).finally(() => {
        inFlight.delete(key);
      });

      inFlight.set(key, started);

      return started;
    },
  };
}

// Maps a Supabase Auth refresh error to rejected/unavailable by name and
// status only (no Supabase import here). Only an explicit answer of the auth
// server counts as a rejection; everything else is "could not confirm".
export function classifyRefreshError(error: {
  name?: string;
  status?: number;
}): "rejected" | "unavailable" {
  if (error.name === "AuthSessionMissingError") {
    return "rejected";
  }

  if (
    error.name === "AuthApiError" &&
    typeof error.status === "number" &&
    [400, 401, 403, 404, 422].includes(error.status)
  ) {
    return "rejected";
  }

  return "unavailable";
}
