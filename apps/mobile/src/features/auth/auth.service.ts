import { supabase } from "../../lib/supabase";

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
  const { data, error } = await supabase.auth.signInWithPassword({
    email: email.trim(),
    password,
  });

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
  const { error } = await supabase.auth.signOut();

  if (error) {
    throw error;
  }
}