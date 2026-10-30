// A scripted authentication world for the 401 / sign-out tests (not imported by
// app code). It models the parts of Supabase Auth that matter for ordering:
// events change the authoritative boundary, sign-in / sign-out are slow
// asynchronous operations that run through the app's operation queue, and
// signOut acts on whatever session is current WHEN IT RUNS (that is the real
// side effect the ownership check must protect).
import { createAuthOperationQueue, createGuardedSessionEnd } from "./auth-operations.ts";
import { SessionBoundary } from "./session-boundary.ts";
import {
  createSessionLifecycle,
  type OwnershipProof,
  type RefreshResult,
  type SessionIdentity,
} from "./session-lifecycle.ts";

export type Deferred<T> = { promise: Promise<T>; resolve: (value: T) => void };

export function deferred<T>(): Deferred<T> {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((done) => { resolve = done; });

  return { promise, resolve };
}

export const tick = (ms = 5) => new Promise((resolve) => setTimeout(resolve, ms));

export function createAuthLab(options: {
  initial: SessionIdentity | null;
  refresh?: () => Promise<RefreshResult>;
  // Called when the refresh would start; defaults to the real in-queue check.
  checkOwnershipInQueue?: boolean;
  boundary?: SessionBoundary;
  // Holds the real signOut side effect until released.
  signOutGate?: Deferred<void>;
}) {
  const lab = {
    resets: 0,
    refreshCalls: 0,
    signOutCalls: 0,
    // The session that was actually current when signOut ran, per call.
    signedOutUsers: [] as string[],
    current: options.initial,
  };
  const boundary = options.boundary ?? new SessionBoundary(() => { lab.resets += 1; });
  const authority = boundary.claimAuthority();
  const queue = createAuthOperationQueue();

  // What AuthProvider's coordinator does for every Supabase auth event.
  function event(session: SessionIdentity | null): void {
    lab.current = session;
    authority.applyAuthEvent(session?.userId ?? null, session?.accessToken ?? null);
  }

  event(options.initial);

  const lifecycle = createSessionLifecycle({
    // Mirrors the app: the refresh runs in a queue slot and verifies ownership first.
    refreshSession: (proof) =>
      queue.run(async () => {
        if (options.checkOwnershipInQueue !== false && !proof.stillOwns()) {
          return { status: "stale" } as const;
        }

        lab.refreshCalls += 1;

        return options.refresh ? options.refresh() : ({ status: "rejected" } as const);
      }),
    endSession: createGuardedSessionEnd({
      queue,
      signOutLocal: async () => {
        await options.signOutGate?.promise;
        lab.signOutCalls += 1;
        lab.signedOutUsers.push(lab.current?.userId ?? "nobody");
        event(null);
      },
    }),
  });

  // The proof a request gets when it starts with `identity` as its session.
  function proofFor(identity: SessionIdentity): OwnershipProof {
    const snapshot = boundary.snapshot();

    return {
      epoch: snapshot.epoch,
      stillOwns: () => boundary.ownsToken(snapshot, identity.userId, identity.accessToken),
    };
  }

  // signInWithPassword: slow, serialized with signOut, ends with an event.
  function signIn(session: SessionIdentity, gate?: Deferred<void>): Promise<void> {
    return queue.run(async () => {
      await gate?.promise;
      event(session);
    });
  }

  return { lab, boundary, queue, lifecycle, event, proofFor, signIn };
}
