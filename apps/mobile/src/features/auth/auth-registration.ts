// Sign-up, password-reset request and confirmation-resend flows, with the Supabase
// calls injected. Pure and Node-testable.
//
// NON-ENUMERATION (copy rule C6). Whether an address already has an account must
// not be learnable from these screens:
//  * sign-up for an existing address and sign-up for a new one (confirmation
//    required) both end in the same "check your email" outcome;
//  * the password-reset request reports the same outcome for known and unknown
//    addresses;
//  * resending a confirmation reports the same outcome whatever the address is.
// Messages are chosen from the CLASS of the failure (auth-errors.ts), never taken
// from the server's text. One thing no client can hide: when the project does NOT
// require email confirmation, a brand-new address is signed in at once while an
// existing one is not. That depends on the Supabase project's settings (staging
// checklist A-02/A-07) and is recorded there.
//
// Nothing here retries: one call per user action. Callers guard double submits
// (createSubmitGuard) and pass `isCurrent` so an answer that arrives after the user
// left the screen or changed is dropped.
import { classifyAuthFailure, weakPasswordReasons } from "./auth-errors.ts";

export const MIN_PASSWORD_LENGTH = 8;
// Supabase hashes the first 72 bytes only; longer input is silently truncated.
export const MAX_PASSWORD_LENGTH = 72;
export const RESEND_COOLDOWN_SECONDS = 60;

export const AUTH_NETWORK_MESSAGE = "Unable to reach the sign-in service. Check your connection and try again.";
export const AUTH_RATE_LIMIT_MESSAGE = "Too many attempts. Please wait a few minutes and try again.";

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function normalizeEmail(value: string): string {
  return value.trim();
}

export function validateEmail(value: string): string | null {
  const email = normalizeEmail(value);

  if (email === "") {
    return "Enter your email address.";
  }

  if (email.length > 254 || !EMAIL_PATTERN.test(email)) {
    return "Enter a valid email address.";
  }

  return null;
}

// Local checks only: the project's own password policy is enforced by Supabase and
// its rejection is shown (weak_password). The minimum here is a floor, not the policy.
export function validateNewPassword(password: string): string | null {
  if (password === "") {
    return "Enter a password.";
  }

  if (password.length < MIN_PASSWORD_LENGTH) {
    return `Use at least ${MIN_PASSWORD_LENGTH} characters.`;
  }

  if (password.length > MAX_PASSWORD_LENGTH) {
    return `Use at most ${MAX_PASSWORD_LENGTH} characters.`;
  }

  return null;
}

export type SignUpFieldErrors = { email?: string; password?: string; confirm?: string };

export function validateSignUpForm(input: { email: string; password: string; confirm: string }): SignUpFieldErrors {
  const errors: SignUpFieldErrors = {};
  const email = validateEmail(input.email);
  const password = validateNewPassword(input.password);

  if (email) {
    errors.email = email;
  }

  if (password) {
    errors.password = password;
  } else if (input.confirm !== input.password) {
    errors.confirm = "The passwords do not match.";
  }

  return errors;
}

export type ResetFieldErrors = { password?: string; confirm?: string };

export function validateResetForm(input: { password: string; confirm: string }): ResetFieldErrors {
  const errors: ResetFieldErrors = {};
  const password = validateNewPassword(input.password);

  if (password) {
    errors.password = password;
  } else if (input.confirm !== input.password) {
    errors.confirm = "The passwords do not match.";
  }

  return errors;
}

// One in-flight submit at a time. Checked synchronously in the press handler, so two
// quick taps cannot both pass before React re-renders.
export function createSubmitGuard() {
  let busy = false;

  return {
    tryStart(): boolean {
      if (busy) {
        return false;
      }

      busy = true;

      return true;
    },
    end(): void {
      busy = false;
    },
  };
}

// Seconds left before the next resend is allowed (0 = allowed).
export function resendSecondsLeft(sentAtMs: number | null, nowMs: number): number {
  if (sentAtMs === null) {
    return 0;
  }

  const left = RESEND_COOLDOWN_SECONDS - Math.floor((nowMs - sentAtMs) / 1000);

  return Math.min(RESEND_COOLDOWN_SECONDS, Math.max(0, left));
}

type AuthResponse = { data: { session: unknown | null } | null; error: unknown };
type PlainResponse = { error: unknown };

export type SignUpOutcome =
  // The project does not require confirmation: a session already exists.
  | { kind: "signed_in" }
  // Confirmation email requested (also the answer for an address that already has an account).
  | { kind: "check_email"; email: string }
  // The input was refused; shown next to the field.
  | { kind: "rejected"; field: "email" | "password"; message: string }
  | { kind: "failed"; message: string }
  // The user left or changed while the call ran: nothing to show.
  | { kind: "stale" };

export type SignUpDeps = {
  signUp: (params: { email: string; password: string; options: { emailRedirectTo: string } }) => Promise<AuthResponse>;
  redirectTo: string;
  isCurrent: () => boolean;
};

function weakPasswordMessage(error: unknown): string {
  const reasons = weakPasswordReasons(error);

  return reasons.length > 0
    ? `That password is not strong enough: ${reasons.join(", ")}.`
    : "That password is not strong enough. Try a longer one with a mix of characters.";
}

export async function registerAccount(
  deps: SignUpDeps,
  input: { email: string; password: string },
): Promise<SignUpOutcome> {
  const email = normalizeEmail(input.email);
  let response: AuthResponse;

  try {
    response = await deps.signUp({ email, password: input.password, options: { emailRedirectTo: deps.redirectTo } });
  } catch (error) {
    response = { data: null, error };
  }

  if (!deps.isCurrent()) {
    return { kind: "stale" };
  }

  if (!response.error) {
    return response.data?.session ? { kind: "signed_in" } : { kind: "check_email", email };
  }

  switch (classifyAuthFailure(response.error)) {
    // Same outcome as a new address that needs confirmation (C6).
    case "user_exists":
      return { kind: "check_email", email };
    case "weak_password":
      return { kind: "rejected", field: "password", message: weakPasswordMessage(response.error) };
    case "invalid_email":
      return { kind: "rejected", field: "email", message: "Enter a valid email address." };
    case "rate_limited":
      return { kind: "failed", message: AUTH_RATE_LIMIT_MESSAGE };
    case "network":
      return { kind: "failed", message: AUTH_NETWORK_MESSAGE };
    case "signup_disabled":
      return { kind: "failed", message: "Creating accounts is not available right now." };
    default:
      return { kind: "failed", message: "We could not create your account. Please try again." };
  }
}

// Shared by "forgot password" and "resend confirmation": the same neutral outcome
// for any address.
export type NeutralSendOutcome =
  | { kind: "sent"; email: string }
  | { kind: "rejected"; message: string }
  | { kind: "failed"; message: string }
  | { kind: "stale" };

async function neutralSend(
  call: () => Promise<PlainResponse>,
  email: string,
  isCurrent: () => boolean,
  fallback: string,
): Promise<NeutralSendOutcome> {
  let response: PlainResponse;

  try {
    response = await call();
  } catch (error) {
    response = { error };
  }

  if (!isCurrent()) {
    return { kind: "stale" };
  }

  if (!response.error) {
    return { kind: "sent", email };
  }

  switch (classifyAuthFailure(response.error)) {
    // An account-related refusal must not look different from success.
    case "user_exists":
    case "session_missing":
      return { kind: "sent", email };
    case "invalid_email":
      return { kind: "rejected", message: "Enter a valid email address." };
    case "rate_limited":
      return { kind: "failed", message: AUTH_RATE_LIMIT_MESSAGE };
    case "network":
      return { kind: "failed", message: AUTH_NETWORK_MESSAGE };
    default:
      return { kind: "failed", message: fallback };
  }
}

export type PasswordResetDeps = {
  resetPasswordForEmail: (email: string, options: { redirectTo: string }) => Promise<PlainResponse>;
  redirectTo: string;
  isCurrent: () => boolean;
};

export function requestPasswordReset(deps: PasswordResetDeps, rawEmail: string): Promise<NeutralSendOutcome> {
  const email = normalizeEmail(rawEmail);

  return neutralSend(
    () => deps.resetPasswordForEmail(email, { redirectTo: deps.redirectTo }),
    email,
    deps.isCurrent,
    "We could not send the link. Please try again.",
  );
}

export type ResendDeps = {
  resend: (params: { type: "signup"; email: string; options: { emailRedirectTo: string } }) => Promise<PlainResponse>;
  redirectTo: string;
  isCurrent: () => boolean;
};

export function resendConfirmation(deps: ResendDeps, rawEmail: string): Promise<NeutralSendOutcome> {
  const email = normalizeEmail(rawEmail);

  return neutralSend(
    () => deps.resend({ type: "signup", email, options: { emailRedirectTo: deps.redirectTo } }),
    email,
    deps.isCurrent,
    "We could not send the email. Please try again.",
  );
}
