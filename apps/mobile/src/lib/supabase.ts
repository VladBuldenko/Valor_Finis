import { AppState, Platform } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { createClient, processLock } from "@supabase/supabase-js";
import "react-native-url-polyfill/auto";

import { queueSessionMutations } from "../api/auth-gateway";
import { createFetchWithTimeout } from "../api/fetch-with-timeout";
import { env } from "../config/env";
import { authOperations } from "./auth-queue";

// Bounds every Supabase request. A sign-out holds the auth operation queue while
// its server call is in flight, so an unanswered request must not block signing
// in again.
const SUPABASE_REQUEST_TIMEOUT_MS = 20_000;

// The unguarded client. ONLY the session runtime may use it (for the sign-out that
// already runs inside the auth operation queue); a scan test enforces this.
export const rawSupabase = createClient(
  env.supabaseUrl,
  env.supabasePublishableKey,
  {
    auth: {
      ...(Platform.OS !== "web"
        ? {
            storage: AsyncStorage,
          }
        : {}),
      autoRefreshToken: true,
      persistSession: true,
      detectSessionInUrl: false,
      // Email links (sign-up confirmation, password recovery) carry a one-time code
      // that only THIS device can exchange (the code verifier is stored here). The
      // default implicit flow puts a ready-made session in the link, which anybody
      // could send to a victim (login CSRF). Password sign-in is unaffected. See
      // docs/modules/mobile-auth.md.
      flowType: "pkce",
      lock: processLock,
    },
    global: {
      fetch: createFetchWithTimeout(
        (input, init) => fetch(input, init),
        SUPABASE_REQUEST_TIMEOUT_MS,
      ),
    },
  },
);

const guardedAuth = queueSessionMutations(rawSupabase.auth, authOperations);

// What the app imports. Every call that can store or end a session (sign-in,
// sign-up, setSession, refreshSession, signOut, ...) is serialized through
// authOperations, so nothing can slip between a guarded sign-out's ownership
// check and its side effect (MF2-SR09, api/auth-gateway.ts).
export const supabase = new Proxy(rawSupabase, {
  get(target, property) {
    if (property === "auth") {
      return guardedAuth;
    }

    const value: unknown = Reflect.get(target, property, target);

    return typeof value === "function"
      ? (value as (...args: unknown[]) => unknown).bind(target)
      : value;
  },
});

if (Platform.OS !== "web") {
  AppState.addEventListener("change", (state) => {
    if (state === "active") {
      supabase.auth.startAutoRefresh();
    } else {
      supabase.auth.stopAutoRefresh();
    }
  });
}