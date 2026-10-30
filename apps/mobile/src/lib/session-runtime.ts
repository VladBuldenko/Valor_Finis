// App-wide wiring of the session boundary and the 401 lifecycle to Supabase,
// TanStack Query and the navigation-intent store. Imported by the API client
// and the auth provider so both talk to the same instances.
import { navigationIntent } from "../features/auth/navigation-intent";
import { SessionBoundary } from "../api/session-boundary";
import { createGuardedSessionEnd, createQueuedRefresh } from "../api/auth-operations";
import { createSessionLifecycle } from "../api/session-lifecycle";
import { SessionQueryClient } from "./session-query-client";
import { authOperations } from "./auth-queue";
import { rawSupabase } from "./supabase";

export const sessionQueryClient = new SessionQueryClient();

export const sessionBoundary = new SessionBoundary(() => {
  sessionQueryClient.rotate();
});

// For code that continues after an await: false once the user it started for
// is gone. Pass the client obtained from useQueryClient() while rendering.
export const isCurrentQueryClient = sessionQueryClient.isCurrent;

export const sessionLifecycle = createSessionLifecycle({
  // Runs in a queue slot and verifies ownership first (api/auth-operations.ts).
  // Inside the slot the UNGUARDED client is used.
  refreshSession: createQueuedRefresh({
    queue: authOperations,
    refresh: () => rawSupabase.auth.refreshSession(),
    onRejected: () => {
      // The auth layer may end the session itself while rejecting the refresh,
      // so the location is saved here, before anything signs out. A deliberate
      // sign-out or a different user discards it again.
      navigationIntent.captureOnInvalidation();
    },
  }),

  // Ownership is re-checked inside the queue, immediately before the side
  // effect. This already runs inside a queue slot, so it must use the UNGUARDED
  // client (the guarded one would queue behind itself). Every other session
  // change is queued by the guarded client, so nothing can interleave with it.
  endSession: createGuardedSessionEnd({
    queue: authOperations,
    signOutLocal: async () => {
      await rawSupabase.auth.signOut({ scope: "local" });
    },
  }),
});
