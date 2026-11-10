// App-wide wiring of the password-recovery state and the auth-link handler to the
// guarded Supabase client and the session boundary. Imported by the auth provider,
// the root layout, the native-intent hook and the auth service so they all talk to
// the same instances (same pattern as session-runtime.ts).
import AsyncStorage from "@react-native-async-storage/async-storage";

import { appScheme } from "../config/app-scheme";
import { buildAuthRedirectUrl } from "../features/auth/auth-link";
import { createAuthLinkHandler, type LinkAuth } from "../features/auth/auth-link-handler";
import { createRecoveryPersistence } from "../features/auth/recovery-persistence";
import { createRecoveryState } from "../features/auth/recovery-state";
import { bindRecoveryPersistence, createStartupResolver } from "../features/auth/recovery-startup";
import { endSessionVerified, sessionBoundary } from "./session-runtime";
import { supabase } from "./supabase";

// The app starts with the recovery state CLOSED ("resolving") until the persisted
// record of a recovery that was in progress has been resolved against the restored
// session (recovery-startup.ts). Nothing protected is shown or loaded before that.
export const recoveryState = createRecoveryState({ initialPhase: "resolving" });

const recoveryPersistence = createRecoveryPersistence(AsyncStorage);

// Keeps the durable record in step with the state (active / idle).
bindRecoveryPersistence(recoveryState, recoveryPersistence);

const startupResolver = createStartupResolver({
  persistence: recoveryPersistence,
  recovery: recoveryState,
  currentUserId: () => sessionBoundary.snapshot().userId,
  // Local sign-out through the guarded session end: only while the restored session is
  // still the current one, inside the auth operation queue.
  endRestoredSession: (userId) => {
    const snapshot = sessionBoundary.snapshot();

    return endSessionVerified({ epoch: snapshot.epoch, stillOwns: () => sessionBoundary.ownsSession(snapshot, userId) });
  },
});

// Called by the auth provider with every settled authentication state (`userId` null =
// signed out; `restoreFailed` = the stored session could not be read, so "no session"
// may only mean "not loaded yet"). The first call resolves what a recovery that was in
// progress when the process ended means; see recovery-startup.ts.
export function onSettledAuthState(userId: string | null, restoreFailed: boolean): void {
  startupResolver.onAuthState(userId, restoreFailed);
}

export const authRedirectUrl = buildAuthRedirectUrl(appScheme);

// The exchange stores a session, so it goes through the guarded client, i.e. the
// auth operation queue (api/auth-gateway.ts). Only PKCE codes are exchanged.
const linkAuth: LinkAuth = {
  exchangeCodeForSession: async (code) => {
    const { data, error } = await supabase.auth.exchangeCodeForSession(code);
    const redirectType = (data as { redirectType?: unknown }).redirectType;

    return {
      data: { session: data.session, redirectType: typeof redirectType === "string" ? redirectType : null },
      error,
    };
  },
};

export const authLinkHandler = createAuthLinkHandler({
  parse: { schemes: [appScheme], allowExpoDevLinks: __DEV__ },
  auth: linkAuth,
  currentUserId: () => sessionBoundary.snapshot().userId,
  recovery: recoveryState,
  // Awaited before every exchange: a process that dies after it leaves evidence.
  beforeExchange: (context) => recoveryPersistence.writeVerifying(context),
});
