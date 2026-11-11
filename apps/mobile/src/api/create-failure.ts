// What the user is told when an Income or Expense create fails (VF-MVP-CORE-002).
//
// A failed create is not always a create that did not happen: when the response
// is lost (no connection, timeout, an unreadable body, a gateway error) the
// server may already have saved the record. Those outcomes are reported as
// UNKNOWN, never as "not saved", and the form keeps the request's key so a
// second tap replays the original instead of adding a second record. Pure (no
// React Native) so the wording rules are tested in Node.
import { isApiError } from "./api-error.ts";
import { getApiErrorMessage } from "./api-error-message.ts";

export type CreateFailure = {
  title: string;
  message: string;
  // The request may have been saved even though the response was lost.
  outcomeUnknown: boolean;
  // The key can no longer be used for this request (the backend answered that it
  // identifies a different one): the next submission must get a fresh key.
  discardAttempt: boolean;
};

export function describeCreateFailure(
  error: unknown,
  noun: "income" | "expense",
  fallbackMessage: string,
): CreateFailure {
  if (isApiError(error)) {
    // A gateway answer (502/503/504) says nothing about what the app server did,
    // so it is outcome-unknown. The app's OWN 503 carries a domain code (for
    // example fx_provider_unavailable): it was raised before anything was
    // written, so it is a definite failure and keeps its specific message.
    const domainCode = error.code !== null && error.code !== "service_unavailable";
    const gatewayError =
      error.kind === "http" &&
      (error.status === 502 || error.status === 503 || error.status === 504) &&
      !domainCode;

    if (
      error.kind === "network" ||
      error.kind === "timeout" ||
      error.kind === "malformed_response" ||
      error.kind === "cancelled" ||
      gatewayError
    ) {
      return {
        title: "Could not confirm",
        message:
          `We could not confirm whether the ${noun} was saved. Check your list, or tap Save again: ` +
          "a repeated save of the same entry is recognized and will not be recorded twice.",
        outcomeUnknown: true,
        discardAttempt: false,
      };
    }

    if (error.kind === "http" && error.status === 409 && error.code === `${noun}_idempotency_conflict`) {
      return {
        title: `Create ${noun} failed`,
        message: `This entry clashes with an earlier submission. Check your ${noun} list, then try again.`,
        outcomeUnknown: false,
        discardAttempt: true,
      };
    }
  }

  return {
    title: `Create ${noun} failed`,
    message: getApiErrorMessage(error, fallbackMessage),
    outcomeUnknown: false,
    discardAttempt: false,
  };
}
