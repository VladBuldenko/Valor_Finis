// VF-GOALS-PLANNING-002A: wording for "Compared with your financial history".
// Pure and Node-testable. Every amount is the backend's own string from
// GET /goals/{id}/plan/history-comparison: nothing is calculated, rounded or
// compared as money here (the sign of a difference is read from the backend's
// difference_direction; a leading "-" is only dropped for display).
// The comparison is about RECORDED PAST activity: it never says the
// installment is affordable or that any money is available.
import type { GoalHistoryComparison, GoalHistoryLimitation, GoalHistoryMonth } from "./goal.types.ts";

export const HISTORY_TITLE = "Compared with your financial history";

export const HISTORY_DISCLAIMER =
  "This is based on recorded past activity, not a guarantee that the contribution is affordable.";

// What the comparison does not model, always shown (the backend always sends
// both "not modelled" codes).
export const HISTORY_NOT_MODELLED =
  "Budget limits are not counted as spending, and money already reserved for Goals or set aside by active Rules is not subtracted.";

const money = (amount: string, currency: string): string => `${amount} ${currency}`;
const withoutSign = (amount: string): string => amount.replace(/^-/, "");

// "the last 3 completed months", or, when months with no recorded income and
// expenses were left out (never counted as zero), how many were used.
function periodPhrase(monthsUsed: number): string {
  return monthsUsed === 3
    ? "the last 3 completed months"
    : `${monthsUsed} of the last 3 completed months (months without recorded income and expenses are left out)`;
}

// "Your recorded monthly net flow averaged ..." or null when no average is shown.
function averageSentence(c: GoalHistoryComparison): string | null {
  if (c.average_monthly_net_flow === null) {
    return null;
  }

  return `Your recorded monthly net flow averaged ${money(c.average_monthly_net_flow, c.base_currency)} over ${periodPhrase(c.months_used)}.`;
}

function requirementSentence(c: GoalHistoryComparison): string | null {
  return c.required_per_installment === null
    ? null
    : `Your Goal requires ${money(c.required_per_installment, c.goal_currency)} per installment.`;
}

function differenceSentence(c: GoalHistoryComparison): string | null {
  if (c.historical_difference === null || c.difference_direction === null) {
    return null;
  }

  switch (c.difference_direction) {
    case "surplus":
      return `On that history, your average was ${money(withoutSign(c.historical_difference), c.base_currency)} above the required installment.`;
    case "shortfall":
      return `On that history, your average was ${money(withoutSign(c.historical_difference), c.base_currency)} below the required installment.`;
    case "equal":
      return "On that history, your average matched the required installment.";
    default: {
      const exhaustive: never = c.difference_direction;

      return String(exhaustive);
    }
  }
}

const LIMITATION_MESSAGES: Partial<Record<GoalHistoryLimitation, (c: GoalHistoryComparison) => string>> = {
  unresolved_currency_data: (c) =>
    `Some recorded income or expenses in these months have no amount in your base currency (${c.base_currency}), so no average is shown.`,
  fewer_than_two_active_months: () =>
    "A comparison needs at least 2 of the last 3 completed months with both recorded income and recorded expenses. Record more to see one.",
};

// The sentences to show, in order. Always at least one.
export function historySentences(c: GoalHistoryComparison): string[] {
  const average = averageSentence(c);
  const requirement = requirementSentence(c);

  switch (c.status) {
    case "comparable":
      return [average, requirement, differenceSentence(c)].filter((line): line is string => line !== null);
    case "insufficient_data": {
      const reasons = c.limitations.flatMap((code) => {
        const message = LIMITATION_MESSAGES[code];

        return message ? [message(c)] : [];
      });

      return [
        reasons.length > 0 ? reasons.join(" ") : "There is not enough recorded history to compare yet.",
        ...(requirement ? [requirement] : []),
      ];
    }
    case "currency_mismatch":
      return [
        `This Goal is in ${c.goal_currency}, but your recorded income and expenses are in ${c.base_currency}. They are not converted, so no comparison is shown.`,
        ...(average ? [average] : []),
        ...(requirement ? [requirement] : []),
      ];
    case "no_required_installment":
      return [
        "This Goal has no required installment right now, so there is nothing to compare.",
        ...(average ? [average] : []),
      ];
    default: {
      const exhaustive: never = c.status;

      return [String(exhaustive)];
    }
  }
}

export type HistoryMonthRow = { label: string; value: string };

// One compact row per analysed month: its net flow, or that nothing was
// recorded, and whether it counts toward the average.
export function historyMonthRows(c: GoalHistoryComparison): HistoryMonthRow[] {
  return c.months.map((month: GoalHistoryMonth) => {
    const unresolved = month.unresolved_income_count + month.unresolved_expense_count > 0;
    const recorded = month.income_count + month.expense_count > 0 || unresolved;
    const net = money(month.net_flow, c.base_currency);
    let value: string;

    if (!recorded) {
      value = "no recorded income or expenses";
    } else if (unresolved) {
      value = `${net} net, counting only records with a ${c.base_currency} amount; not in the average`;
    } else {
      value = `${net} net${month.included_in_average ? "" : ", not in the average"}`;
    }

    return { label: month.period_start.slice(0, 7), value };
  });
}
