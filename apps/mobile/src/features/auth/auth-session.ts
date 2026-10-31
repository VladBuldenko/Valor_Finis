// The AuthProvider effect, without React: start listening to authentication,
// restore the stored session, and return the cleanup. Kept separate so the exact
// lifecycle (including StrictMode's setup / cleanup / setup) runs in tests with
// a fake auth client.
import type { SessionBoundary } from "../../api/session-boundary.ts";
import {
  createAuthCoordinator,
  type AuthSessionLike,
  type AuthState,
} from "./auth-coordinator.ts";

export type AuthClientLike<S extends AuthSessionLike> = {
  getSession: () => Promise<{ data: { session: S | null }; error: unknown }>;
  onAuthStateChange: (callback: (event: string, session: S | null) => void) => {
    data: { subscription: { unsubscribe: () => void } };
  };
};

export function startAuthSession<S extends AuthSessionLike>(deps: {
  auth: AuthClientLike<S>;
  boundary: Pick<SessionBoundary, "claimAuthority">;
  publish: (state: AuthState<S>) => void;
  onRestoreError?: (error: unknown) => void;
}): () => void {
  // The newest claim is the only one that may change the boundary.
  const coordinator = createAuthCoordinator<S>({
    authority: deps.boundary.claimAuthority(),
    publish: deps.publish,
  });
  // Taken before the await: an auth event that arrives meanwhile wins.
  const settle = coordinator.beginInitialRestore();

  deps.auth.getSession().then(
    ({ data, error }) => {
      if (error) {
        deps.onRestoreError?.(error);
      }

      settle(data.session);
    },
    (error: unknown) => {
      deps.onRestoreError?.(error);
      settle(null);
    },
  );

  // Synchronous on purpose: no Supabase Auth call may be made in here.
  const {
    data: { subscription },
  } = deps.auth.onAuthStateChange((_event, session) => {
    coordinator.handleAuthEvent(session);
  });

  return () => {
    coordinator.dispose();
    subscription.unsubscribe();
  };
}
