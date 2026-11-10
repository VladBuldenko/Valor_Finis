// Whether the app is in the middle of a password recovery, and for WHICH user. Pure
// and Node-testable (the React side reads it through useSyncExternalStore).
//
// A recovery link produces a real Supabase session. Until the user has chosen a new
// password that session must not open the app's data screens (journey J20), so the
// navigator asks this store:
//
//   resolving  the app has just started: a recovery that was in progress when the
//              process ended is being looked up (recovery-startup.ts). Closed, like
//              verifying: nothing protected is shown or loaded until it is resolved
//   deferred   startup could not judge a recorded recovery (the restore failed): signed
//              out as far as the app knows, and a session that appears is NOT shown
//              as an app session until the record has been judged (closed like resolving)
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
  | { readonly phase: "resolving" }
  | { readonly phase: "deferred" }
  | { readonly phase: "idle" }
  | { readonly phase: "verifying" }
  | { readonly phase: "active"; readonly userId: string };

export type RecoveryState = ReturnType<typeof createRecoveryState>;

const RESOLVING: RecoverySnapshot = { phase: "resolving" };
const DEFERRED: RecoverySnapshot = { phase: "deferred" };
const IDLE: RecoverySnapshot = { phase: "idle" };
const VERIFYING: RecoverySnapshot = { phase: "verifying" };

export type StartupResolution = { kind: "idle" } | { kind: "deferred" } | { kind: "active"; userId: string };

// `initialPhase: "resolving"` is what the app uses: the state starts closed until the
// startup resolution has run. Tests of the link logic may start `idle`.
export function createRecoveryState(options: { initialPhase?: "idle" | "resolving" } = {}) {
  let snapshot: RecoverySnapshot = options.initialPhase === "resolving" ? RESOLVING : IDLE;
  // A link arrived while the startup resolution was still running.
  let linkWaiting = false;
  let generation = 0;
  // The user whose recovery was active when a newer link attempt began (or whose
  // recovery session an attempt found). If that attempt ends without a session of its
  // own the recovery must still be in force: a failed, expired or replayed link must
  // never release a recovery session into the app.
  let previous: string | null = null;
  // The state before the running attempt was "deferred": it returns there when the
  // attempt ends without a recovery session of its own.
  let previousDeferred = false;
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

      // Still resolving the previous run: stay closed; the resolution hands over to
      // this attempt when it finishes (finishResolving).
      if (snapshot.phase === "resolving") {
        linkWaiting = true;

        return generation;
      }

      if (snapshot.phase === "active") {
        previous = snapshot.userId;
      }

      if (snapshot.phase === "deferred") {
        previousDeferred = true;
      }

      set(VERIFYING);

      return generation;
    },

    // The startup resolution is done: `result` is the recovery to resume (or none).
    // `currentUserId` is the authoritative current user NOW; a recovery that is not
    // for that user is dropped, so it can never gate (or be mistaken for) a later,
    // ordinary sign-in.
    finishResolving(result: StartupResolution, currentUserId: string | null): void {
      if (snapshot.phase !== "resolving") {
        return;
      }

      const base: StartupResolution =
        result.kind === "active" && result.userId !== currentUserId ? { kind: "idle" } : result;

      if (linkWaiting) {
        linkWaiting = false;
        previous = base.kind === "active" ? base.userId : null;
        previousDeferred = base.kind === "deferred";
        set(VERIFYING);

        return;
      }

      set(base.kind === "active" ? { phase: "active", userId: base.userId } : base.kind === "deferred" ? DEFERRED : IDLE);
    },

    // Closes the gate again to judge a recorded recovery that startup deferred, once a
    // session exists. Only from "deferred".
    reopen(): boolean {
      if (snapshot.phase !== "deferred") {
        return false;
      }

      linkWaiting = false;
      set(RESOLVING);

      return true;
    },

    // The user whose recovery is in force (active, or remembered while a newer
    // attempt runs); null when none. Persisted before every exchange.
    recoveryUserId: (): string | null =>
      snapshot.phase === "active" ? snapshot.userId : previous,

    isCurrent: (attempt: number): boolean => attempt === generation,

    // The newest attempt produced a recovery session for `userId`.
    activate(attempt: number, userId: string): boolean {
      if (attempt !== generation || snapshot.phase !== "verifying") {
        return false;
      }

      previous = null;
      previousDeferred = false;
      set({ phase: "active", userId });

      return true;
    },

    // The newest attempt ended without a recovery session of its own. A recovery that
    // was in force before it stays in force.
    finish(attempt: number): void {
      if (attempt === generation && snapshot.phase === "resolving") {
        linkWaiting = false;

        return;
      }

      if (attempt === generation && snapshot.phase === "verifying") {
        const restored = previous;
        const wasDeferred = previousDeferred;

        previous = null;
        previousDeferred = false;
        set(restored !== null ? { phase: "active", userId: restored } : wasDeferred ? DEFERRED : IDLE);
      }
    },

    // A recovery session of `userId` exists and is the current session, but the
    // attempt that created it was superseded. Keep the gate closed for it.
    keepRecovery(userId: string): void {
      if (snapshot.phase === "resolving") {
        return;
      }

      if (snapshot.phase === "verifying") {
        previous = userId;
      } else {
        previousDeferred = false;
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
  if (input.isLoading || input.recovery.phase === "verifying" || input.recovery.phase === "resolving") {
    return "loading";
  }

  // A recorded recovery that startup could not judge: never the app while a session exists.
  if (input.recovery.phase === "deferred") {
    return input.userId === null ? "signed-out" : "loading";
  }

  if (input.userId === null) {
    return "signed-out";
  }

  if (input.recovery.phase === "active" && input.recovery.userId === input.userId) {
    return "recovery";
  }

  return "app";
}
