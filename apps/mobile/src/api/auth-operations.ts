// Serializes every app-initiated change of the Supabase session (sign-in,
// sign-out, ending an invalidated session) so that a stale decision cannot sign
// out a session that was established while it waited (MF2-SR07).
//
// WHY A QUEUE. supabase.auth.signOut() reads the stored session, calls the server
// and then removes whatever is stored at that moment. The ownership check in front
// of it is only meaningful if no OTHER session change can happen between the check
// and the removal. Verified on @supabase/auth-js 2.112.3: sign-in calls do not take
// the client's lock, so the library does not provide that exclusion; the app does,
// by serializing every session-changing call through this queue.
//
// That is enforced by construction, not convention: the client the app imports
// (lib/supabase.ts) is wrapped by api/auth-gateway.ts so that every call that can
// store, replace or end a session runs in this queue; the unguarded client is
// imported only by the session runtime, which already runs inside a queue slot
// (a scan test enforces this, and a classification test fails if an auth-js
// upgrade adds an unclassified public method).
//
// Residual, accepted: the library's own background work (auto-refresh tick,
// foreground recovery, initialization) is not queued. It only acts on the stored
// session, so it can move it to a newer token of the SAME user or end it, never
// establish a different user; a sign-out that follows hits the same user's
// (refreshed) session or nothing. Tested on the real library in
// auth-js-integration.test.ts.
import {
  classifyRefreshError,
  type OwnershipProof,
  type RefreshOutcome,
} from "./session-lifecycle.ts";

export type AuthOperationQueue = {
  run: <T>(operation: () => Promise<T>) => Promise<T>;
};

export function createAuthOperationQueue(): AuthOperationQueue {
  let tail: Promise<unknown> = Promise.resolve();

  return {
    run<T>(operation: () => Promise<T>): Promise<T> {
      const result = tail.then(operation, operation);

      // A failing operation must not block the ones behind it.
      tail = result.catch(() => undefined);

      return result;
    },
  };
}

export function createGuardedSessionEnd(deps: {
  queue: AuthOperationQueue;
  signOutLocal: () => Promise<void>;
}): (proof: OwnershipProof) => Promise<"signed-out" | "stale"> {
  return (proof) =>
    deps.queue.run(async () => {
      // First thing once the queue is ours: authoritative, synchronous check.
      if (!proof.stillOwns()) {
        return "stale";
      }

      await deps.signOutLocal();

      return "signed-out";
    });
}

export type RefreshCall = () => Promise<{
  data: { session: { user: { id: string }; access_token: string } | null };
  error: { name?: string; status?: number } | null;
}>;

// The refresh step of the 401 flow. It runs in a queue slot and verifies
// ownership first: refreshing acts on whichever session is current when the slot
// is reached, which may no longer be the one whose token was rejected. `refresh`
// must be the UNGUARDED client's call (the guarded one would queue behind itself).
export function createQueuedRefresh(deps: {
  queue: AuthOperationQueue;
  refresh: RefreshCall;
  // Called when the auth server rejected the refresh, before anything signs out.
  onRejected: () => void;
}): (proof: OwnershipProof) => Promise<RefreshOutcome> {
  return (proof) =>
    deps.queue.run(async (): Promise<RefreshOutcome> => {
      if (!proof.stillOwns()) {
        return { status: "stale" };
      }

      const { data, error } = await deps.refresh();

      if (error) {
        const outcome = classifyRefreshError(error);

        if (outcome === "rejected") {
          deps.onRejected();
        }

        return { status: outcome };
      }

      return data.session
        ? {
            status: "refreshed",
            session: { userId: data.session.user.id, accessToken: data.session.access_token },
          }
        : { status: "rejected" };
    });
}
