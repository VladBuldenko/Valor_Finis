// VF-GOALS-PLANNING-001: wording for the "Goal plan" section. Pure and
// Node-testable. Every amount and date here is the backend's own string from
// POST /goals/{id}/plan: nothing is calculated, rounded or compared as money
// (the one numeric look is an exact string check for "no overfunding").
// The plan is advisory: it never says a plan is affordable or certain.
import { isZeroMoney } from "./goal-partitions.ts";
import type { GoalPlan, GoalPlanWhatIf } from "./goal.types.ts";

export const PLAN_TITLE = "Goal plan";

// The one documented schedule, stated wherever the required amount is shown.
export const PLAN_ASSUMPTION =
  "This is an estimate. It does not look at your income or spending, and nothing is scheduled, reserved or moved. It assumes one contribution today and one on the 1st of each following month, up to the target date.";

export const PROGRESS_NOTE =
  "Tracked progress is not money set aside in an Account. Reserved progress is earmarked inside an Account; it does not move money out of it.";

export const WHAT_IF_TITLE = "Try a monthly amount";
export const WHAT_IF_HINT = "Enter an amount per installment to see roughly when the target could be reached.";
export const WHAT_IF_DISCLAIMER = "An estimate, not a promise.";

export type PlanRow = { label: string; value: string };

const money = (amount: string, currency: string): string => `${amount} ${currency}`;
const installments = (count: number): string => `${count} installment${count === 1 ? "" : "s"}`;

// Remaining (never negative: the backend clamps it) and, only for an
// overfunded Goal, by how much it is over.
export function planProgressRows(plan: GoalPlan): PlanRow[] {
  const rows: PlanRow[] = [{ label: "Remaining to target", value: money(plan.remaining_amount, plan.currency) }];

  if (!isZeroMoney(plan.overfunded_amount)) {
    rows.push({ label: "Above target by", value: money(plan.overfunded_amount, plan.currency) });
  }

  return rows;
}

// What to say about this Goal's situation instead of a required amount, or
// null when a required amount is shown.
export function planStatusMessage(plan: GoalPlan): string | null {
  switch (plan.plan_status) {
    case "archived":
      return "This Goal is archived, so it takes no new contributions and no plan is shown.";
    case "already_funded":
      return isZeroMoney(plan.overfunded_amount)
        ? "This Goal has reached its target."
        : "This Goal is already above its target.";
    case "no_target_date":
      return "Add a target date to see how much to set aside on each installment.";
    case "target_date_passed":
      return `The target date (${plan.target_date ?? "unknown"}) has passed. Update it to plan ahead.`;
    case "ready":
      return null;
    default: {
      const exhaustive: never = plan.plan_status;

      return String(exhaustive);
    }
  }
}

// The required installment, or null unless the backend returned one.
export function planRequirement(plan: GoalPlan): { headline: string; schedule: string } | null {
  if (
    plan.plan_status !== "ready" ||
    plan.required_per_installment === null ||
    plan.installment_count === null ||
    plan.first_installment_date === null ||
    plan.last_installment_date === null
  ) {
    return null;
  }

  return {
    headline: `${money(plan.required_per_installment, plan.currency)} per installment`,
    schedule: `${installments(plan.installment_count)}, from ${plan.first_installment_date} to ${plan.last_installment_date}, to reach the target by ${plan.target_date ?? "the target date"}.`,
  };
}

// The sentence for a what-if result; always ends by saying it is an estimate.
export function whatIfMessage(whatIf: GoalPlanWhatIf, plan: GoalPlan): string {
  const amount = money(whatIf.monthly_contribution, plan.currency);

  switch (whatIf.outcome) {
    case "reaches_target": {
      const timing =
        whatIf.on_or_before_target_date === true
          ? " That is on or before the target date."
          : whatIf.on_or_before_target_date === false
            ? " That is after the target date."
            : "";
      const count = whatIf.installments_needed === null ? "" : ` (${installments(whatIf.installments_needed)})`;

      return `At ${amount} per installment the target could be reached around ${whatIf.estimated_completion_date ?? "an unknown date"}${count}.${timing}`;
    }
    case "no_contribution":
      return "An amount of zero never reaches the target. Try an amount above zero.";
    case "not_reachable_within_horizon":
      return `At ${amount} per installment the target would take more than ${plan.horizon_months} months, so no date is shown.`;
    case "already_funded":
      return "Nothing is left to reach: this Goal is at or above its target.";
    case "not_applicable":
      return "An archived Goal takes no contributions, so there is nothing to estimate.";
    default: {
      const exhaustive: never = whatIf.outcome;

      return String(exhaustive);
    }
  }
}
