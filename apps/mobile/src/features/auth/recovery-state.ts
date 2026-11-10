// Whether the app is in the middle of a password recovery, and for WHICH user. Pure
// and Node-testable (the React side reads it through useSyncExternalStore).
//
// A recovery link produces a real Supabase session. Until the user has chosen a new
// password that session must not open the app's data screens (journey J20), so the
// navigator asks this store:
//
//   idle       nothing to do
//   verifying  a link is being turned into a session (show a neutral loading state)
//   active     the session of `userId` is a recovery session: only the reset screen
//
// Rules that keep a stale result from taking effect:
//  * Every link attempt gets a generation. Only the newest attempt may finish or
//    activate; an older one that resolves late is ignored (`stale`).
//  * `active` belongs to ONE user. `reconcile` is fed the authoritative current user
//    from the auth coordinator; any other user (or nobody) ends the recovery, so a
//    recovery can never carry over to a different account.

export type RecoverySnapshot =
  | { readonly phase: "idle" }
  | { readonly phase: "verifying" }
  | { readonly phase: "active"; readonly userId: string };

export type RecoveryState = ReturnType<typeof createRecoveryState>;

const IDLE: RecoverySnapshot = { phase: "idle" };
const VERIFYING: RecoverySnapshot = { phase: "verifying" };

export function createRecoveryState() {
  let snapshot: RecoverySnapshot = IDLE;
  let generation = 0;
  // The user whose recovery was active when a newer link attempt began (or whose
  // recovery session an attempt found). If that attempt ends without a session of its
  // own the recovery must still be in force: a failed, expired or replayed link must
  // never release a recovery session into the app.
  let previous: string | null = null;
  const listeners = new Set<() => void>();

  function set(next: RecoverySnapshot): void {
    if (next === snapshot) {
      return;
    }

    snapshot = next;
    listeners.forEach((listener) => listener());
  }

  return {
    getSnapshot: (): RecoverySnapshot => snapshot,

    subscribe(listener: () => void): () => void {
      listeners.add(listener);

      return () => {
        listeners.delete(listener);
      };
    },

    // A link is about to be verified. Supersedes every earlier attempt (and an
    // `active` recovery: a newer link replaces it).
    begin(): number {
      generation += 1;

      if (snapshot.phase === "active") {
        previous = snapshot.userId;
      }

      set(VERIFYING);

      return generation;
    },

    isCurrent: (attempt: number): boolean => attempt === generation,

    // The newest attempt produced a recovery session for `userId`.
    activate(attempt: number, userId: string): boolean {
      if (attempt !== generation || snapshot.phase !== "verifying") {
        return false;
      }

      previous = null;
      set({ phase: "active", userId });

      return true;
    },

    // The newest attempt ended without a recovery session of its own. A recovery that
    // was in force before it stays in force.
    finish(attempt: number): void {
      if (attempt === generation && snapshot.phase === "verifying") {
        const restored = previous;

        previous = null;
        set(restored === null ? IDLE : { phase: "active", userId: restored });
      }
    },

    // A recovery session of `userId` exists and is the current session, but the
    // attempt that created it was superseded. Keep the gate closed for it.
    keepRecovery(userId: string): void {
      if (snapshot.phase === "verifying") {
        previous = userId;
      } else {
        set({ phase: "active", userId });
      }
    },

    // The password was changed (or the recovery was cancelled) for `userId`.
    complete(userId: string): void {
      if (previous === userId) {
        previous = null;
      }

      if (snapshot.phase === "active" && snapshot.userId === userId) {
        set(IDLE);
      }
    },

    // The authoritative current user (null = nobody). A recovery that belongs to
    // somebody else no longer applies.
    reconcile(currentUserId: string | null): void {
      if (previous !== null && previous !== currentUserId) {
        previous = null;
      }

      if (snapshot.phase === "active" && snapshot.userId !== currentUserId) {
        set(IDLE);
      }
    },
  };
}

// Where the root navigator should be, from the two facts it has. Pure so the
// protected-route decision is tested without React.
export type RootRoute = "loading" | "signed-out" | "recovery" | "app";

export function decideRootRoute(input: {
  isLoading: boolean;
  userId: string | null;
  recovery: RecoverySnapshot;
}): RootRoute {
  if (input.isLoading || input.recovery.phase === "verifying") {
    return "loading";
  }

  if (input.userId === null) {
    return "signed-out";
  }

  if (input.recovery.phase === "active" && input.recovery.userId === input.userId) {
    return "recovery";
  }

  return "app";
}
