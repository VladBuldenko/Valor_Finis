// Serializes every app-initiated change of the Supabase session (sign-in,
// sign-out, ending an invalidated session) so that a stale decision cannot sign
// out a session that was established while it waited (MF2-SR07).
//
// WHY A QUEUE. supabase.auth.signOut() acts on whatever session is current when
// it runs. The ownership check in front of it is only meaningful if no other
// session change can happen between the check and the side effect, so
// everything that can replace the session in this app goes through the SAME
// queue, and the end-session operation re-checks ownership as the first thing
// it does once it holds the queue. Any new auth-mutating call (sign-up,
// recovery, MF-4) MUST be added through `run`.
//
// Residual window, accepted: between the re-check and signOut taking Supabase's
// internal lock, only an auth event from outside this queue could intervene. A
// same-user TOKEN refresh in that window cannot make the sign-out wrong, because
// the refresh token of that session was just rejected by the auth server, so no
// valid refreshed token can exist.
import type { OwnershipProof } from "./session-lifecycle.ts";

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
