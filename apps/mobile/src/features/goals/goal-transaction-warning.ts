// The advisory minimum-floor warning of a successful manual reservation
// (VF-020F2, M08). The backend response is the ONLY authority: nothing here
// compares amounts, predicts a warning or does arithmetic on money -- the
// decimal strings are rendered exactly as returned.
import type {
  GoalTransactionCreated,
  GoalTransactionFloorWarning,
} from "./goal.types";

export const FLOOR_WARNING_TITLE = "Reserved, below your minimum";

// The first floor warning in the response, or null. Absent, empty or
// unrecognised warnings give null: no warning is ever invented.
export function findFloorWarning(
  response: Pick<GoalTransactionCreated, "warnings">,
): GoalTransactionFloorWarning | null {
  const warnings = response.warnings;

  if (!Array.isArray(warnings)) {
    return null;
  }

  return (
    warnings.find((warning) => warning?.code === "minimum_unallocated_floor") ??
    null
  );
}

// Plain wording: the reservation succeeded; the floor is a guide, not a
// limit; the figures are the backend's. A reservation only earmarks money
// inside the Account -- nothing is sent anywhere.
export function buildFloorWarningMessage(
  warning: GoalTransactionFloorWarning,
  currency: string,
): string {
  return [
    "Your reservation was saved.",
    `After it, ${warning.projected_reservable_amount} ${currency} is available to reserve on this Account, below your minimum unallocated floor of ${warning.minimum_unallocated_floor} ${currency}.`,
    `Available for rules: ${warning.projected_rule_capacity} ${currency}.`,
    "The floor is a guide, not a limit, and the Account balance did not change.",
  ].join("\n\n");
}

export type GoalTransactionSuccessDeps = {
  response: GoalTransactionCreated;
  currency: string;
  // Resets the form and the idempotency attempts.
  resetForm: () => void;
  // Shows the warning (e.g. Alert.alert). Called at most once.
  presentWarning: (title: string, message: string) => void;
  // Refreshes Goals, Goal transactions, Goal Progress and (linked) Accounts.
  invalidate: () => Promise<unknown>;
};

// 201 (new) and 200 (exact replay) are handled identically. The warning is
// presented BEFORE the cache refresh is awaited, so a slow or failing refetch
// cannot swallow it, and nothing here re-sends the request.
export async function handleGoalTransactionSuccess(
  deps: GoalTransactionSuccessDeps,
): Promise<void> {
  const warning = findFloorWarning(deps.response);

  deps.resetForm();

  if (warning) {
    deps.presentWarning(
      FLOOR_WARNING_TITLE,
      buildFloorWarningMessage(warning, deps.currency),
    );
  }

  await deps.invalidate();
}
