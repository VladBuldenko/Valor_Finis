import Constants from "expo-constants";

import { isAppSpecificScheme } from "../features/auth/auth-link";

// The app's URL scheme, from app.json (`expo.scheme`), the single source of truth.
// Auth emails return to `<scheme>://auth/callback`; that exact URL must be in the
// Supabase project's redirect allowlist (a hosted setting, see
// docs/operations/staging/supabase-auth-checklist.md, item A-05).
function readScheme(): string {
  const configured = Constants.expoConfig?.scheme;
  const scheme = Array.isArray(configured) ? configured[0] : configured;

  if (!isAppSpecificScheme(scheme)) {
    throw new Error("expo.scheme in app.json must be an app-specific URL scheme.");
  }

  return scheme;
}

export const appScheme = readScheme();
