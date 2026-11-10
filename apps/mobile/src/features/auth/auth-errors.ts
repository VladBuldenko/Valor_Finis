// Classifies what Supabase Auth reported, WITHOUT ever using its message text.
// Pure and Node-testable (structural checks only: no @supabase import).
//
// Why not the message: auth-js messages are written for developers and some reveal
// account state ("User already registered", "Email not confirmed"). The sign-up and
// recovery screens must not tell a visitor whether an address has an account
// (copy rule C6), and no message may carry a credential, so every screen shows copy
// chosen from the CLASS returned here, never `error.message`.

export type AuthFailureClass =
  | "network" // unreachable, timeout, 5xx: nothing was decided; trying again later is fine
  | "rate_limited"
  | "user_exists" // sign-up for an address that already has an account
  | "weak_password"
  | "same_password"
  | "invalid_email"
  | "signup_disabled"
  | "session_missing" // the session that must authorize the request is gone or expired
  | "link_expired" // an auth link/code that is expired or already used
  | "other";

type ErrorLike = { name?: unknown; code?: unknown; status?: unknown };

function field(error: unknown): ErrorLike {
  return typeof error === "object" && error !== null ? (error as ErrorLike) : {};
}

const RATE_LIMIT_CODES = new Set([
  "over_email_send_rate_limit",
  "over_request_rate_limit",
  "over_sms_send_rate_limit",
]);
const USER_EXISTS_CODES = new Set(["user_already_exists", "email_exists"]);
const INVALID_EMAIL_CODES = new Set(["email_address_invalid", "validation_failed"]);
const SESSION_CODES = new Set([
  "session_not_found",
  "session_expired",
  "refresh_token_not_found",
  "refresh_token_already_used",
  "bad_jwt",
  "no_authorization",
  "user_not_found",
]);
const LINK_CODES = new Set([
  "otp_expired",
  "otp_disabled",
  "flow_state_not_found",
  "flow_state_expired",
  "bad_code_verifier",
  "bad_oauth_callback",
  "invalid_grant",
]);

export function classifyAuthFailure(error: unknown): AuthFailureClass {
  const { name, code, status } = field(error);

  if (name === "AuthRetryableFetchError") {
    return "network";
  }

  if (name === "AuthWeakPasswordError" || code === "weak_password") {
    return "weak_password";
  }

  if (name === "AuthSessionMissingError") {
    return "session_missing";
  }

  if (typeof code === "string") {
    if (RATE_LIMIT_CODES.has(code)) {
      return "rate_limited";
    }

    if (USER_EXISTS_CODES.has(code)) {
      return "user_exists";
    }

    if (code === "same_password") {
      return "same_password";
    }

    if (INVALID_EMAIL_CODES.has(code)) {
      return "invalid_email";
    }

    if (code === "signup_disabled" || code === "email_provider_disabled") {
      return "signup_disabled";
    }

    if (SESSION_CODES.has(code)) {
      return "session_missing";
    }

    if (LINK_CODES.has(code)) {
      return "link_expired";
    }
  }

  if (status === 429) {
    return "rate_limited";
  }

  if (typeof status === "number" && status >= 500) {
    return "network";
  }

  // A thrown non-auth error (fetch aborted by the timeout wrapper, offline): the
  // request did not reach a decision.
  if (name === "AbortError" || name === "TypeError") {
    return "network";
  }

  return "other";
}

// The reasons a weak-password rejection lists, as fixed phrases (the server's own
// wording is not shown).
export function weakPasswordReasons(error: unknown): string[] {
  const reasons = (error as { reasons?: unknown } | null)?.reasons;

  if (!Array.isArray(reasons)) {
    return [];
  }

  const phrases: string[] = [];

  for (const reason of reasons) {
    if (reason === "length") {
      phrases.push("make it longer");
    } else if (reason === "characters") {
      phrases.push("mix letters, numbers and symbols");
    } else if (reason === "pwned") {
      phrases.push("avoid a password that appeared in a data leak");
    }
  }

  return phrases;
}
