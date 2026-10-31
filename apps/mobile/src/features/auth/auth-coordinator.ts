// The single place where authentication changes become app state. It decides
// ORDER (a stale initial restore never overwrites a newer auth event), makes
// every adoption flow through the session boundary BEFORE the UI sees it, and
// owns ITS OWN LIFETIME: one coordinator belongs to one mounted AuthProvider
// effect and becomes inert for good when that effect is cleaned up.
//
// Rules:
//  * Supabase's onAuthStateChange events are authoritative and applied in
//    arrival order.
//  * The initial getSession() restore is only a claim made at a point in time:
//    if any auth event arrived after it started, its result is discarded
//    (including a sign-out during restoration).
//  * After `dispose()` (effect cleanup) or once a newer coordinator claimed the
//    boundary authority, nothing this coordinator receives or resolves, a late
//    restore, a late event of a disposed subscription, can change the boundary
//    or publish state (MF2-SR08).
//  * The event handler is synchronous and never calls back into Supabase Auth
//    (supabase-js can deadlock on re-entrant auth calls inside the callback).

export type AuthState<S> = {
  session: S | null;
  isLoading: boolean;
};

export type AuthSessionLike = {
  user: { id: string };
  access_token: string;
};

export type AuthorityLike = {
  applyAuthEvent: (userId: string | null, accessToken: string | null) => boolean;
  isActive: () => boolean;
  release: () => void;
};

export type AuthCoordinatorDeps<S extends AuthSessionLike> = {
  authority: AuthorityLike;
  publish: (state: AuthState<S>) => void;
};

export function createAuthCoordinator<S extends AuthSessionLike>(
  deps: AuthCoordinatorDeps<S>,
) {
  // Counts applied auth events; an initial restore compares it with the value
  // it started at.
  let eventVersion = 0;
  let disposed = false;

  const isLive = () => !disposed && deps.authority.isActive();

  function adopt(session: S | null): void {
    deps.authority.applyAuthEvent(session?.user.id ?? null, session?.access_token ?? null);
    deps.publish({ session, isLoading: false });
  }

  return {
    handleAuthEvent(session: S | null): void {
      if (!isLive()) {
        return;
      }

      eventVersion += 1;
      adopt(session);
    },

    // Call BEFORE starting the asynchronous restore; call the returned function
    // with its result.
    beginInitialRestore(): (restored: S | null) => void {
      const startedAt = eventVersion;

      return (restored) => {
        if (!isLive() || eventVersion !== startedAt) {
          return;
        }

        eventVersion += 1;
        adopt(restored);
      };
    },

    // Effect cleanup: this coordinator may never act again.
    dispose(): void {
      disposed = true;
      deps.authority.release();
    },
  };
}
