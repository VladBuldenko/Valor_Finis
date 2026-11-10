// Setting the new password after a recovery link. Pure and dependency-injected.
//
// The Supabase `updateUser` call acts on WHICHEVER session is stored when it runs.
// A recovery screen that was opened for user A must never change the password of
// user B who signed in a moment later, so the call is made through
// `createGuardedPasswordUpdate` (api/auth-operations.ts): it runs in the auth
// operation queue, verifies ownership first, and only then calls Supabase. This
// module adds the outcome mapping around it.
//
// One call per submit and no automatic retry. A lost answer is NOT reported as a
// success or a failure: the screen says it could not confirm, and the user may submit
// again (setting the same password twice is harmless).
import { classifyAuthFailure, weakPasswordReasons } from "./auth-errors.ts";
import { AUTH_NETWORK_MESSAGE, AUTH_RATE_LIMIT_MESSAGE } from "./auth-registration.ts";

export type PasswordUpdateOutcome =
  | { kind: "updated" }
  // The user/session changed before the call could run: nothing was changed.
  | { kind: "stale" }
  | { kind: "rejected"; message: string }
  // The recovery session expired or was revoked: a new link is needed.
  | { kind: "session_expired" }
  | { kind: "failed"; message: string };

export type GuardedUpdateResult = { status: "stale" } | { status: "done"; error: unknown };

export type PasswordUpdateDeps = {
  update: (password: string) => Promise<GuardedUpdateResult>;
  // False once the screen/user the submit started for is gone (a failure is then dropped).
  isCurrent: () => boolean;
};

export async function updateRecoveredPassword(
  deps: PasswordUpdateDeps,
  password: string,
): Promise<PasswordUpdateOutcome> {
  let result: GuardedUpdateResult;

  try {
    result = await deps.update(password);
  } catch (error) {
    result = { status: "done", error };
  }

  if (result.status === "stale") {
    return { kind: "stale" };
  }

  // A change that succeeded is reported as such even if the screen is gone: the
  // caller must still end the recovery. Only a failure of a departed screen is dropped.
  if (!result.error) {
    return { kind: "updated" };
  }

  if (!deps.isCurrent()) {
    return { kind: "stale" };
  }

  switch (classifyAuthFailure(result.error)) {
    case "weak_password": {
      const reasons = weakPasswordReasons(result.error);

      return {
        kind: "rejected",
        message:
          reasons.length > 0
            ? `That password is not strong enough: ${reasons.join(", ")}.`
            : "That password is not strong enough. Try a longer one with a mix of characters.",
      };
    }
    case "same_password":
      return { kind: "rejected", message: "Choose a password that is different from your current one." };
    case "session_missing":
    case "link_expired":
      return { kind: "session_expired" };
    case "rate_limited":
      return { kind: "failed", message: AUTH_RATE_LIMIT_MESSAGE };
    case "network":
      return {
        kind: "failed",
        message: `${AUTH_NETWORK_MESSAGE} We could not confirm whether the password was changed.`,
      };
    default:
      return { kind: "failed", message: "We could not change your password. Please try again." };
  }
}
