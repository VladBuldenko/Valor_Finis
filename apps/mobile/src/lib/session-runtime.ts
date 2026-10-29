// App-wide wiring of the session boundary and the 401 lifecycle to Supabase,
// TanStack Query and the navigation-intent store. Imported by the API client
// and the auth provider so both talk to the same instances.
import { navigationIntent } from "../features/auth/navigation-intent";
import { SessionBoundary } from "../api/session-boundary";
import {
  classifyRefreshError,
  createSessionLifecycle,
  type SessionIdentity,
} from "../api/session-lifecycle";
import { queryClient, resetPrivateQueryData } from "./query-client";
import { supabase } from "./supabase";

export const sessionBoundary = new SessionBoundary(() => {
  resetPrivateQueryData(queryClient);
});

async function getCurrentSession(): Promise<SessionIdentity | null> {
  const {
    data: { session },
  } = await supabase.auth.getSession();

  return session
    ? { userId: session.user.id, accessToken: session.access_token }
    : null;
}

export const sessionLifecycle = createSessionLifecycle({
  getCurrentSession,

  async refreshSession() {
    const { data, error } = await supabase.auth.refreshSession();

    if (error) {
      const outcome = classifyRefreshError(error);

      if (outcome === "rejected") {
        // The auth layer may end the session itself while rejecting the
        // refresh, so the location is saved here, before anything signs out.
        // A deliberate sign-out or a different user discards it again.
        navigationIntent.captureOnInvalidation();
      }

      return { status: outcome };
    }

    return data.session
      ? {
          status: "refreshed",
          session: { userId: data.session.user.id, accessToken: data.session.access_token },
        }
      : { status: "rejected" };
  },

  async endSession() {
    // Local scope: the server already rejected this session, so no revoke call
    // is needed (or possible).
    await supabase.auth.signOut({ scope: "local" });
  },
});
