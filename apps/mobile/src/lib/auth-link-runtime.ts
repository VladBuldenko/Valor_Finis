// App-wide wiring of the password-recovery state and the auth-link handler to the
// guarded Supabase client and the session boundary. Imported by the auth provider,
// the root layout, the native-intent hook and the auth service so they all talk to
// the same instances (same pattern as session-runtime.ts).
import { appScheme } from "../config/app-scheme";
import { buildAuthRedirectUrl } from "../features/auth/auth-link";
import { createAuthLinkHandler, type LinkAuth } from "../features/auth/auth-link-handler";
import { createRecoveryState } from "../features/auth/recovery-state";
import { sessionBoundary } from "./session-runtime";
import { supabase } from "./supabase";

export const recoveryState = createRecoveryState();

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
});
