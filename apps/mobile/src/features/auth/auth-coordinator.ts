// The single place where authentication changes become app state. It decides
// ORDER (a stale initial restore never overwrites a newer auth event) and makes
// every adoption flow through the session boundary BEFORE the UI sees it, so no
// screen can render for a user the boundary has not adopted.
//
// Rules:
//  * Supabase's onAuthStateChange events are authoritative and applied in
//    arrival order.
//  * The initial getSession() restore is only a claim made at a point in time:
//    if any auth event arrived after it started, its result is discarded
//    (including a sign-out during restoration).
//  * The event handler is synchronous and never calls back into Supabase Auth
//    (supabase-js can deadlock on re-entrant auth calls inside the callback).

export type AuthState<S> = {
  session: S | null;
  isLoading: boolean;
};

export type AuthCoordinatorDeps<S extends { user: { id: string } }> = {
  boundary: { applyAuthEvent: (userId: string | null) => boolean };
  publish: (state: AuthState<S>) => void;
};

export function createAuthCoordinator<S extends { user: { id: string } }>(
  deps: AuthCoordinatorDeps<S>,
) {
  // Counts applied auth events; an initial restore compares it with the value
  // it started at.
  let eventVersion = 0;

  function adopt(session: S | null): void {
    deps.boundary.applyAuthEvent(session?.user.id ?? null);
    deps.publish({ session, isLoading: false });
  }

  return {
    handleAuthEvent(session: S | null): void {
      eventVersion += 1;
      adopt(session);
    },

    // Call BEFORE starting the asynchronous restore; call the returned function
    // with its result.
    beginInitialRestore(): (restored: S | null) => void {
      const startedAt = eventVersion;

      return (restored) => {
        if (eventVersion !== startedAt) {
          return;
        }

        eventVersion += 1;
        adopt(restored);
      };
    },
  };
}
