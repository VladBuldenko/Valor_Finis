// Decides what a HTTP 401 means for the session. Pure and dependency-injected
// (no Supabase / React Native import) so the concurrency rules are testable.
//
// OWNERSHIP, NOT LOOKUPS. Whether the failed token still belongs to the active
// session is decided by the synchronous `proof.stillOwns()` (session-boundary:
// same epoch, same user, same CURRENT access token, all driven by authoritative
// auth events). An asynchronous "who is signed in?" lookup is never consulted:
// its answer can be stale by the time it resolves, and acting on it signed out
// the wrong user (MF2-SR07).
//
// Rules:
//  * A 401 only matters if its token is still the active session's token in the
//    same generation. A newer token, another user, or a later A -> B -> A
//    generation makes it stale.
//  * Ownership is re-checked after every asynchronous step and, in `endSession`,
//    again immediately before the sign-out side effect (auth-operations.ts).
//  * Simultaneous 401s for one token (and generation) share ONE check.
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

// What the refresh step may answer. "stale": ownership was lost before the
// refresh could start (it must then not touch whichever session is current).
export type RefreshOutcome = RefreshResult | { status: "stale" };

export type UnauthorizedOutcome =
  | "stale"
  | "refreshed"
  | "signed-out"
  | "unconfirmed";

// Proof that a request belonged to an authentication generation.
export type OwnershipProof = {
  // The authentication epoch the request started in (part of the dedupe key).
  epoch: number;
  // Synchronous and authoritative: true only while the request's token is still
  // the current session's token in the request's epoch.
  stillOwns: () => boolean;
};

export type SessionLifecycleDeps = {
  // Must verify `proof.stillOwns()` as its first step once it holds the auth
  // operation queue: refreshing acts on the session that is current THEN.
  refreshSession: (proof: OwnershipProof) => Promise<RefreshOutcome>;
  // Ends the local session, but only if `proof` still holds at the moment the
  // side effect starts. Resolves "stale" when it no longer does.
  endSession: (proof: OwnershipProof) => Promise<"signed-out" | "stale">;
};

export type SessionLifecycle = {
  handleUnauthorized: (
    used: SessionIdentity,
    proof: OwnershipProof,
  ) => Promise<UnauthorizedOutcome>;
};

export function createSessionLifecycle(deps: SessionLifecycleDeps): SessionLifecycle {
  const inFlight = new Map<string, Promise<UnauthorizedOutcome>>();

  async function check(
    used: SessionIdentity,
    proof: OwnershipProof,
  ): Promise<UnauthorizedOutcome> {
    if (!proof.stillOwns()) {
      return "stale";
    }

    const refreshed = await deps.refreshSession(proof);

    if (refreshed.status === "stale") {
      return "stale";
    }

    if (refreshed.status === "unavailable") {
      return "unconfirmed";
    }

    if (refreshed.status === "refreshed") {
      // A new token means the session itself is alive. The same token coming
      // back proves nothing, so it is not treated as a recovery.
      return refreshed.session.accessToken === used.accessToken ? "unconfirmed" : "refreshed";
    }

    // The auth server rejected the refresh. Sign out only if the rejected
    // session is STILL the active one (it may have been replaced or already
    // ended by the auth layer while the refresh was running).
    if (!proof.stillOwns()) {
      return "stale";
    }

    return deps.endSession(proof);
  }

  return {
    handleUnauthorized(used, proof) {
      const key = `${proof.epoch}:${used.userId}:${used.accessToken}`;
      const pending = inFlight.get(key);

      if (pending) {
        return pending;
      }

      const started = check(used, proof).finally(() => {
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
