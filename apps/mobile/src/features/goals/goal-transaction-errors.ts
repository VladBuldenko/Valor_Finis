// Operation-aware error copy for Goal transaction creates (VF-020C3).
//
// The backend has no structured error codes: a domain error is an HTTP
// status plus an exact "detail" string. This maps the KNOWN pairs, using the
// operation context (tracked or linked, contribution or withdrawal), to the
// user-facing copy and to the follow-up the screen must perform. Anything
// unknown falls through to the backend's own detail, then to the caller's
// fallback - raw "API request failed: ..." text is never produced here.
// Pure and framework-free so it can be tested with the Node test runner.

export const GOAL_NOT_FOUND_DETAIL = "Goal not found.";
export const ACCOUNT_NOT_FOUND_DETAIL = "Account not found.";
export const GOAL_ARCHIVED_DETAIL = "Archived goal cannot receive contributions.";
export const ACCOUNT_ARCHIVED_DETAIL =
  "Archived account cannot receive new transactions.";
export const CAPACITY_DETAIL =
  "Reservation exceeds the Account's reservable capacity.";
export const TRACKED_SHORTFALL_DETAIL =
  "Withdrawal exceeds the current goal balance.";
export const IDEMPOTENCY_CONFLICT_DETAIL =
  "client_request_id has already been used for a different goal transaction.";

export const TRACKED_SHORTFALL_MESSAGE =
  "Withdrawal exceeds the tracked amount of this goal.";
export const IDEMPOTENCY_CONFLICT_MESSAGE =
  "This request conflicts with an earlier one. Close and reopen the form.";

export type GoalTransactionRequestContext = {
  type: "contribution" | "withdrawal";
  // True when the request carried an account_id (a reservation / release).
  isLinked: boolean;
};

export type GoalTransactionFailureHandling = {
  message: string;
  // Re-fetch the Goal list (a stale Goal state was involved).
  refreshGoals: boolean;
  // Re-fetch the Account list (capacity or Account state was stale).
  refreshAccounts: boolean;
  // The selected Account is no longer valid and must be cleared.
  clearSelectedAccount: boolean;
  // The attempt's key identified a conflicting request; drop it AFTER the
  // message has been shown.
  discardAttempt: boolean;
};

/**
 * Maps a failed Goal transaction create to its message and follow-ups.
 *
 * Parameters:
 * - failure: the HTTP status and exact backend detail (status is null for a
 *   non-HTTP failure such as a network error).
 * - context: the operation that failed.
 * - fallbackMessage: shown when nothing more specific is known.
 */
export function mapGoalTransactionFailure(
  failure: { status: number | null; detail: string | null },
  context: GoalTransactionRequestContext,
  fallbackMessage: string,
): GoalTransactionFailureHandling {
  const base: GoalTransactionFailureHandling = {
    message: failure.detail ?? fallbackMessage,
    refreshGoals: false,
    refreshAccounts: false,
    clearSelectedAccount: false,
    discardAttempt: false,
  };

  if (failure.status === 404 && failure.detail === GOAL_NOT_FOUND_DETAIL) {
    return { ...base, refreshGoals: true };
  }

  if (failure.status === 404 && failure.detail === ACCOUNT_NOT_FOUND_DETAIL) {
    return { ...base, refreshAccounts: true, clearSelectedAccount: true };
  }

  if (failure.status === 409) {
    switch (failure.detail) {
      case GOAL_ARCHIVED_DETAIL:
        return { ...base, refreshGoals: true };
      case ACCOUNT_ARCHIVED_DETAIL:
        return { ...base, refreshAccounts: true, clearSelectedAccount: true };
      case CAPACITY_DETAIL:
        return { ...base, message: CAPACITY_DETAIL, refreshAccounts: true };
      case TRACKED_SHORTFALL_DETAIL:
        // Only a tracked withdrawal can hit this; its wording predates
        // partitions, so the tracked amount is named explicitly.
        return context.type === "withdrawal" && !context.isLinked
          ? { ...base, message: TRACKED_SHORTFALL_MESSAGE, refreshGoals: true }
          : base;
      case IDEMPOTENCY_CONFLICT_DETAIL:
        return {
          ...base,
          message: IDEMPOTENCY_CONFLICT_MESSAGE,
          discardAttempt: true,
        };
      default:
        return base;
    }
  }

  return base;
}
