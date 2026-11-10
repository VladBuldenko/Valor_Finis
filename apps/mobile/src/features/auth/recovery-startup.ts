// What to do, at process start, about a password recovery that was in progress when
// the previous process ended. Pure and dependency-injected.
//
// Until this has run the recovery state is `resolving` (recovery-state.ts): the root
// navigator shows a neutral loading state, the protected screens are not mounted and
// no background financial evaluation runs. The restored Supabase session is therefore
// never visible as an app session before this decides.
//
// Decision (marker x restored session), failing CLOSED whenever it cannot be sure:
//
//  marker                                restored session          result
//  none                                  any                        nothing to do
//  any marker                            none, BUT the restore     DEFER: keep the marker, open closed-to-the-app
//                                        itself failed             (signed out) and judge again when a session appears
//  unreadable (corrupt / storage error)  none                       clear the marker
//  unreadable                            any                        END the session (unresolved)
//  active U                              user U                     RESUME the recovery (reset screen)
//  active U                              none / another user        clear the marker (U's recovery is over)
//  verifying (prior P, recovery R)       none                       clear the marker
//  verifying                             user R                     RESUME the recovery of R
//  verifying                             user P (unchanged)         clear the marker (the exchange did not replace the session)
//  verifying                             anybody else               END the session (a session appeared during an
//                                                                   exchange that never finished: it may be a recovery session)
//
// "END the session" = the local sign-out the app already uses for ending a session,
// guarded by an ownership proof, so it cannot end a session established meanwhile. If it
// cannot be done the recovery is resumed instead (the reset screen, with Cancel), never
// the app.
//
// Known, accepted limit: a recovery for the user who was already signed in on the same
// device (prior = recovery session user) is indistinguishable from the ordinary session
// of that user after a crash inside the exchange. That user already had full access, so
// nothing is escalated.
import type { MarkerRead, RecoveryMarker, RecoveryPersistence } from "./recovery-persistence.ts";
import type { RecoveryState } from "./recovery-state.ts";

export type StartupAction =
  | { kind: "none" }
  // The restore itself failed (offline, storage), so "no session" may only mean "not
  // loaded yet": keep the record and look again when a session appears.
  | { kind: "defer" }
  | { kind: "clear" }
  | { kind: "resume"; userId: string }
  | { kind: "end_session" };

export function decideStartupAction(read: MarkerRead, sessionUserId: string | null, restoreFailed = false): StartupAction {
  if (read.kind === "none") {
    return { kind: "none" };
  }

  if (sessionUserId === null && restoreFailed) {
    return { kind: "defer" };
  }

  if (read.kind === "unreadable") {
    return sessionUserId === null ? { kind: "clear" } : { kind: "end_session" };
  }

  const marker: RecoveryMarker = read.marker;

  if (marker.phase === "active") {
    return sessionUserId === marker.userId ? { kind: "resume", userId: marker.userId } : { kind: "clear" };
  }

  if (sessionUserId === null) {
    return { kind: "clear" };
  }

  if (marker.recoveryUserId !== null && sessionUserId === marker.recoveryUserId) {
    return { kind: "resume", userId: marker.recoveryUserId };
  }

  if (marker.priorUserId !== null && sessionUserId === marker.priorUserId) {
    return { kind: "clear" };
  }

  return { kind: "end_session" };
}

export type StartupDeps = {
  persistence: RecoveryPersistence;
  recovery: RecoveryState;
  // The authoritative current user right now (session boundary).
  currentUserId: () => string | null;
  // Ends the restored session locally, only while it is still the one that was
  // restored. "stale" = somebody else is current by now.
  endRestoredSession: (userId: string) => Promise<"signed-out" | "stale">;
};

// Resolves the recovery state. The caller runs it exactly once per process (the
// runtime guards that). `restoredUserId` is the user of the session the auth provider
// restored (null = signed out). Never throws.
export async function resolveRecoveryAtStartup(
  deps: StartupDeps,
  restoredUserId: string | null,
  restoreFailed = false,
): Promise<{ deferred: boolean }> {
  const { recovery, persistence } = deps;
  let action: StartupAction;

  try {
    action = decideStartupAction(await persistence.read(), restoredUserId, restoreFailed);
  } catch {
    action = restoredUserId === null ? { kind: "clear" } : { kind: "end_session" };
  }

  switch (action.kind) {
    case "none":
      recovery.finishResolving({ kind: "idle" }, deps.currentUserId());

      return { deferred: false };
    case "defer":
      // Nobody is signed in as far as the app knows, so the app is not reachable; the
      // record stays, and the state stays "deferred" (a session that shows up is judged
      // before it can be shown), until a session is judged.
      recovery.finishResolving({ kind: "deferred" }, deps.currentUserId());

      return { deferred: true };
    case "clear":
      recovery.finishResolving({ kind: "idle" }, deps.currentUserId());
      await persistence.clear();

      return { deferred: false };
    case "resume":
      recovery.finishResolving({ kind: "active", userId: action.userId }, deps.currentUserId());

      return { deferred: false };
    default:
      break;
  }

  // End the session; the marker stays until it is gone.
  let ended: "signed-out" | "stale" | "failed";

  try {
    ended = await deps.endRestoredSession(restoredUserId as string);
  } catch {
    ended = "failed";
  }

  if (ended === "failed") {
    // Cannot end it: never the app. The reset screen (with Cancel) is the safe place.
    await persistence.writeActive(restoredUserId as string);
    recovery.finishResolving({ kind: "active", userId: restoredUserId as string }, deps.currentUserId());

    return { deferred: false };
  }

  recovery.finishResolving({ kind: "idle" }, deps.currentUserId());
  await persistence.clear();

  return { deferred: false };
}

// Drives the resolution from the auth provider's state changes. `onAuthState` is
// called synchronously with every SETTLED authentication state (never while the first
// restore is still running):
//  * the first call resolves against the restored session;
//  * if that had to be deferred (the restore failed and left a recorded recovery
//    behind), the state is closed again, synchronously and before the app can render,
//    when a session finally appears, and the decision is made then.
export function createStartupResolver(deps: StartupDeps) {
  let started = false;
  let current: Promise<void> = Promise.resolve();

  function run(userId: string | null, restoreFailed: boolean): void {
    // Not inside the auth state callback: the callback must never call back into auth.
    current = Promise.resolve()
      .then(() => resolveRecoveryAtStartup(deps, userId, restoreFailed))
      .then(
        () => undefined,
        () => undefined,
      );
  }

  // A deferred recovery is judged as soon as a session exists and nothing else is
  // running: the gate is closed again synchronously (before anything can render the
  // session), and again whenever a link attempt that was running ends back in "deferred".
  function judgeDeferred(): void {
    const userId = deps.currentUserId();

    if (started && userId !== null && deps.recovery.reopen()) {
      run(userId, false);
    }
  }

  deps.recovery.subscribe(judgeDeferred);

  return {
    // Resolves when the resolution that is running (if any) has finished.
    whenDone: (): Promise<void> => current,

    onAuthState(userId: string | null, restoreFailed: boolean): void {
      if (!started) {
        started = true;
        run(userId, restoreFailed);

        return;
      }

      judgeDeferred();
    },
  };
}

// Keeps the durable record in step with the in-memory state: a recovery that is
// `active` is recorded as such, and an `idle` state removes the record. `verifying` is
// NOT written here: the link handler writes it, awaited, before the exchange.
export function bindRecoveryPersistence(recovery: RecoveryState, persistence: RecoveryPersistence): () => void {
  let last = "";
  let lastPhase: string = recovery.getSnapshot().phase;

  return recovery.subscribe(() => {
    const snapshot = recovery.getSnapshot();
    const signature = snapshot.phase === "active" ? `active:${snapshot.userId}` : snapshot.phase;
    const previousPhase = lastPhase;

    lastPhase = snapshot.phase;

    if (signature === last) {
      return;
    }

    last = signature;

    if (snapshot.phase === "active") {
      void persistence.writeActive(snapshot.userId);
    } else if (snapshot.phase === "idle" && previousPhase !== "resolving") {
      // Leaving "resolving" is the startup resolution's own business: it clears the
      // record itself when the recovery is over, and KEEPS it when it deferred.
      void persistence.clear();
    }
  });
}
