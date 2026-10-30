import { supabase } from "../../lib/supabase";
import { authOperations } from "../../lib/session-runtime";
import { navigationIntent } from "./navigation-intent";

/**
 * Signs in a user with email and password through Supabase Auth.
 *
 * The UI layer should not communicate with Supabase directly.
 * Authentication details are kept inside the auth service.
 */
export async function signInWithEmail(
  email: string,
  password: string,
) {
  // Serialized with every other session change (see auth-operations.ts).
  const { data, error } = await authOperations.run(() =>
    supabase.auth.signInWithPassword({
      email: email.trim(),
      password,
    }),
  );

  if (error) {
    throw error;
  }

  return data.session;
}

/**
 * Signs out the current user through Supabase Auth.
 *
 * Auth state changes are handled globally by AuthProvider.
 */
export async function signOut(): Promise<void> {
  // A deliberate sign-out never restores the previous location on next sign-in.
  navigationIntent.discard();

  const { error } = await authOperations.run(() => supabase.auth.signOut());

  if (error) {
    throw error;
  }
}