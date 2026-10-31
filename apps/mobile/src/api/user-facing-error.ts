// What a user is allowed to read when a request fails. Screens use these
// instead of `error.message`, which for an HTTP failure is the historical
// `API request failed: <status> <raw body>` (kept for compatibility with the
// parsing helpers) and can carry HTML pages, stack traces or JSON envelopes.
//
//  * 5xx: never the body or detail; a neutral message only.
//  * 4xx: the backend's own domain message (string `detail`, or the first
//    validation `msg`) when it is short and not technical; otherwise the
//    caller's fallback. 409 and 422 messages are part of the app's contract.
//  * Network, timeout, malformed response, missing session: fixed texts. The
//    runtime's exception text, URLs, paths and tokens are never shown.
//  * Anything unrecognised: the caller's fallback, never `error.message`.
//
// Structured data (status, detail, kind, code) stays on ApiError / readApiFailure
// for application logic. Error codes (BE-1) are intentionally not used yet.
import { ApiError } from "./api-error.ts";
import { getApiErrorMessage, readApiFailure } from "./api-error-message.ts";

export const SERVER_ERROR_MESSAGE = "Something went wrong on our side. Please try again in a moment.";
export const UNAVAILABLE_MESSAGE = "The service is temporarily unavailable. Please try again in a moment.";
export const NETWORK_ERROR_MESSAGE = "Unable to reach the server. Check your connection and try again.";
export const TIMEOUT_MESSAGE = "The request took too long. Check your connection and try again.";
export const CANCELLED_MESSAGE = "The request was cancelled.";
export const UNREADABLE_MESSAGE = "The server sent an unexpected response. Please try again.";
export const SIGN_IN_AGAIN_MESSAGE = "Your session has expired. Please sign in again.";
export const FORBIDDEN_MESSAGE = "You do not have permission to do that.";
export const AUTH_UNAVAILABLE_MESSAGE =
  "Unable to reach the sign-in service. Check your connection and try again.";

const MAX_DOMAIN_MESSAGE_LENGTH = 300;
// Text that is diagnostics, not a sentence written for a user.
const TECHNICAL = /traceback|exception|stack ?trace|<\/?[a-z!][^>]*>|\bat \S+:\d+|sqlalchemy|psycopg|postgres|\bselect\b.+\bfrom\b|errno|0x[0-9a-f]{6,}|\{\s*"/i;

function isUserSafe(text: string): boolean {
  return text.length > 0 && text.length <= MAX_DOMAIN_MESSAGE_LENGTH && !TECHNICAL.test(text);
}

function messageForStatus(status: number, error: Error, fallback: string): string {
  if (status === 401) {
    return SIGN_IN_AGAIN_MESSAGE;
  }

  if (status === 403) {
    return FORBIDDEN_MESSAGE;
  }

  if (status === 502 || status === 503 || status === 504) {
    return UNAVAILABLE_MESSAGE;
  }

  if (status >= 500) {
    return SERVER_ERROR_MESSAGE;
  }

  const domain = getApiErrorMessage(error, fallback);

  return isUserSafe(domain) ? domain : fallback;
}

export function getUserFacingErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    switch (error.kind) {
      case "timeout":
        return TIMEOUT_MESSAGE;
      case "cancelled":
        return CANCELLED_MESSAGE;
      case "network":
        return NETWORK_ERROR_MESSAGE;
      case "malformed_response":
        return UNREADABLE_MESSAGE;
      case "unauthenticated":
        return SIGN_IN_AGAIN_MESSAGE;
      default:
        return error.status === null ? fallback : messageForStatus(error.status, error, fallback);
    }
  }

  if (error instanceof Error) {
    // A legacy wrapped Error: "API request failed: <status> <body>".
    const { status } = readApiFailure(error);

    if (status !== null) {
      return messageForStatus(status, error, fallback);
    }
  }

  return fallback;
}

// Errors from Supabase Auth (sign-in, sign-out). An AuthApiError carries the
// auth service's own message ("Invalid login credentials"), which is meant for
// the user; connectivity errors get a fixed text; anything else the fallback.
export function getAuthErrorMessage(error: unknown, fallback: string): string {
  if (!(error instanceof Error)) {
    return fallback;
  }

  if (error.name === "AuthApiError" && isUserSafe(error.message)) {
    return error.message;
  }

  if (error.name === "AuthRetryableFetchError") {
    return AUTH_UNAVAILABLE_MESSAGE;
  }

  return fallback;
}
