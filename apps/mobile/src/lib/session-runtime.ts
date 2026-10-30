// App-wide wiring of the session boundary and the 401 lifecycle to Supabase,
// TanStack Query and the navigation-intent store. Imported by the API client
// and the auth provider so both talk to the same instances.
import { navigationIntent } from "../features/auth/navigation-intent";
import { SessionBoundary } from "../api/session-boundary";
import { createAuthOperationQueue, createGuardedSessionEnd } from "../api/auth-operations";
import { classifyRefreshError, createSessionLifecycle } from "../api/session-lifecycle";
import { SessionQueryClient } from "./session-query-client";
import { supabase } from "./supabase";

export const sessionQueryClient = new SessionQueryClient();

export const sessionBoundary = new SessionBoundary(() => {
  sessionQueryClient.rotate();
});

// For code that continues after an await: false once the user it started for
// is gone. Pass the client obtained from useQueryClient() while rendering.
export const isCurrentQueryClient = sessionQueryClient.isCurrent;

// Every app-initiated change of the Supabase session (sign-in, sign-out,
// ending an invalidated session) runs through this queue; see auth-operations.ts.
export const authOperations = createAuthOperationQueue();

export const sessionLifecycle = createSessionLifecycle({
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

  // Ownership is re-checked inside the queue, immediately before the side
  // effect. Local scope: the server already rejected this session, so no revoke
  // call is needed (or possible).
  endSession: createGuardedSessionEnd({
    queue: authOperations,
    signOutLocal: async () => {
      await supabase.auth.signOut({ scope: "local" });
    },
  }),
});
