// App-wide wiring of the session boundary and the 401 lifecycle to Supabase,
// TanStack Query and the navigation-intent store. Imported by the API client
// and the auth provider so both talk to the same instances.
import { navigationIntent } from "../features/auth/navigation-intent";
import { SessionBoundary } from "../api/session-boundary";
import { createGuardedSessionEnd, createQueuedRefresh, createVerifiedLocalSignOut } from "../api/auth-operations";
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

// Ends the local session only while `proof` still holds, inside the auth operation
// queue (used by the 401 flow below and by cancelling a password recovery).
// Inside the queue slot the UNGUARDED client is used.
export const endSessionIfOwned = createGuardedSessionEnd({
  queue: authOperations,
  signOutLocal: async () => {
    await rawSupabase.auth.signOut({ scope: "local" });
  },
});

// Like endSessionIfOwned, but it THROWS unless the session is really gone (see
// createVerifiedLocalSignOut). For cancelling a password recovery and for the startup
// resolution, which remove their durable record only because the session ended.
export const endSessionVerified = createGuardedSessionEnd({
  queue: authOperations,
  signOutLocal: createVerifiedLocalSignOut({
    signOutLocal: () => rawSupabase.auth.signOut({ scope: "local" }),
    currentUserId: () => sessionBoundary.snapshot().userId,
  }),
});

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

  // Ownership is re-checked inside the queue, immediately before the side effect.
  endSession: endSessionIfOwned,
});
