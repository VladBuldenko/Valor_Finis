import { createGuardedPasswordUpdate } from "../../api/auth-operations";
import type { OwnershipProof } from "../../api/session-lifecycle";
import { authRedirectUrl, recoveryState } from "../../lib/auth-link-runtime";
import { authOperations } from "../../lib/auth-queue";
import { endSessionIfOwned, sessionBoundary } from "../../lib/session-runtime";
import { supabase } from "../../lib/supabase";
import {
  registerAccount,
  requestPasswordReset,
  resendConfirmation,
  type NeutralSendOutcome,
  type SignUpOutcome,
} from "./auth-registration";
import { updateRecoveredPassword, type PasswordUpdateOutcome } from "./password-recovery";
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
  // The exported client serializes this with every other session change
  // (api/auth-gateway.ts).
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
  // A deliberate sign-out never restores the previous location on next sign-in.
  navigationIntent.discard();

  const { error } = await supabase.auth.signOut();

  if (error) {
    throw error;
  }
}

// ---------------------------------------------------------------------------
// Sign-up, confirmation, password recovery (MF-4)
//
// Screens never talk to Supabase: they call these functions, which add the
// "is this still the same user and screen?" check (`isMounted` plus the session
// boundary's epoch) so an answer that arrives late is dropped, and which choose
// the messages (never the server's text). One call per action, no automatic retry.
// ---------------------------------------------------------------------------

function currentGuard(isMounted: () => boolean): () => boolean {
  const snapshot = sessionBoundary.snapshot();

  return () => isMounted() && sessionBoundary.isCurrent(snapshot);
}

export function signUpWithEmail(
  email: string,
  password: string,
  isMounted: () => boolean,
): Promise<SignUpOutcome> {
  return registerAccount(
    {
      // A session-changing call: the guarded client queues it (api/auth-gateway.ts).
      signUp: (params) => supabase.auth.signUp(params),
      redirectTo: authRedirectUrl,
      isCurrent: currentGuard(isMounted),
    },
    { email, password },
  );
}

export function sendPasswordResetEmail(email: string, isMounted: () => boolean): Promise<NeutralSendOutcome> {
  return requestPasswordReset(
    {
      resetPasswordForEmail: (address, options) => supabase.auth.resetPasswordForEmail(address, options),
      redirectTo: authRedirectUrl,
      isCurrent: currentGuard(isMounted),
    },
    email,
  );
}

export function resendConfirmationEmail(email: string, isMounted: () => boolean): Promise<NeutralSendOutcome> {
  return resendConfirmation(
    {
      resend: (params) => supabase.auth.resend(params),
      redirectTo: authRedirectUrl,
      isCurrent: currentGuard(isMounted),
    },
    email,
  );
}

const updatePasswordGuarded = createGuardedPasswordUpdate({
  queue: authOperations,
  update: (password) => supabase.auth.updateUser({ password }),
});

// Ownership of the recovery session the screen was opened for. Null when there is
// no active recovery (nothing may change a password then).
function recoveryProof(): { proof: OwnershipProof; userId: string } | null {
  const recovery = recoveryState.getSnapshot();
  const snapshot = sessionBoundary.snapshot();

  if (recovery.phase !== "active" || snapshot.userId !== recovery.userId) {
    return null;
  }

  const userId = recovery.userId;

  return {
    userId,
    proof: { epoch: snapshot.epoch, stillOwns: () => sessionBoundary.ownsSession(snapshot, userId) },
  };
}

export async function setRecoveredPassword(
  password: string,
  isMounted: () => boolean,
): Promise<PasswordUpdateOutcome> {
  const owned = recoveryProof();

  if (!owned) {
    return { kind: "stale" };
  }

  const outcome = await updateRecoveredPassword(
    {
      update: (value) => updatePasswordGuarded(owned.proof, value),
      isCurrent: currentGuard(isMounted),
    },
    password,
  );

  // The recovery ends only for the user it belongs to, and only if still theirs.
  if (outcome.kind === "updated" && owned.proof.stillOwns()) {
    recoveryState.complete(owned.userId);
  }

  return outcome;
}

// Leaves the recovery without choosing a password: the recovery session is ended
// on this device (local scope: the user's other devices stay signed in).
export async function cancelRecovery(): Promise<"cancelled" | "stale"> {
  const owned = recoveryProof();

  if (!owned) {
    return "stale";
  }

  navigationIntent.discard();

  const result = await endSessionIfOwned(owned.proof);

  if (result === "signed-out") {
    recoveryState.complete(owned.userId);

    return "cancelled";
  }

  return "stale";
}
