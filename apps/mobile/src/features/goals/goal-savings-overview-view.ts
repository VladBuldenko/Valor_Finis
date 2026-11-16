// VF-GOALS-PLANNING-002B: wording for the "Savings plans" overview on the Goals
// list. Pure and Node-testable. Every amount, count and status here is the
// backend's own answer from GET /goals/savings-overview: nothing is added,
// rounded or compared as money on the device (the sign of a difference is read
// from the backend's difference_direction; a leading "-" is only dropped for
// display, and counts are integers the backend sent or array lengths).
// The overview is about HYPOTHETICAL required installments next to RECORDED
// past activity: it never says an installment is scheduled, reserved or moved,
// and never that the user can afford it.
import type { GoalSavingsMonth, GoalSavingsOverview } from "./goal.types.ts";

export const OVERVIEW_TITLE = "Savings plans";

// The one schedule assumption, stated wherever the installments are shown.
export const OVERVIEW_ASSUMPTION =
  "These are hypothetical required installments, not scheduled contributions. Each Goal with a target date is spread over one installment today and one on the 1st of each following month, up to its target date. Nothing is scheduled, set aside or moved.";

// What the overview does not model, always shown.
export const OVERVIEW_NOT_MODELLED =
  "Budget limits, recurring bills and other future obligations are not counted, and neither is money already reserved for Goals or set aside by active Rules.";

export const OVERVIEW_DISCLAIMER =
  "This is based on recorded past activity and hypothetical installments. It is not a promise that these amounts fit your finances.";

const money = (amount: string, currency: string): string => `${amount} ${currency}`;
const withoutSign = (amount: string): string => amount.replace(/^-/, "");
const goals = (count: number): string => `${count} Goal${count === 1 ? "" : "s"}`;
const verb = (count: number, singular: string, plural: string): string => (count === 1 ? singular : plural);

// True when there is anything to say: a planned Goal, or an active Goal that is
// unplanned (no/passed target date) or left out for its currency. A user with
// no Goals, or only funded, completed or archived ones, sees no section.
export function hasOverviewContent(overview: GoalSavingsOverview): boolean {
  const { no_target_date, target_date_passed, other_currency } = overview.exclusions;

  return overview.planned_goals.length > 0 || no_target_date + target_date_passed + other_currency > 0;
}

// The current month: the first month of the window.
function thisMonth(overview: GoalSavingsOverview): GoalSavingsMonth | null {
  return overview.months[0] ?? null;
}

// "the last 3 completed months", or, when months with no recorded income and
// expenses were left out (never counted as zero), how many were used.
function periodPhrase(monthsUsed: number): string {
  return monthsUsed === 3
    ? "the last 3 completed months"
    : `${monthsUsed} of the last 3 completed months (months without recorded income and expenses are left out)`;
}

// The headline: this month's combined required installment, or null when no
// Goal is planned. The amount is the backend's string, shown as given.
export function overviewHeadline(overview: GoalSavingsOverview): { label: string; amount: string } | null {
  const month = thisMonth(overview);

  if (month === null || overview.planned_goals.length === 0) {
    return null;
  }

  return {
    label: "This month's combined required installment",
    amount: money(month.total_required, overview.base_currency),
  };
}

// The sentences under the headline: how many Goals are planned, that the total
// is incomplete when Goals were left out, or that nothing is planned.
export function overviewSummaryLines(overview: GoalSavingsOverview): string[] {
  const month = thisMonth(overview);
  const planned = overview.planned_goals.length;

  if (month === null || planned === 0) {
    return ["No Goal has a required installment right now."];
  }

  const lines = [
    planned === month.planned_goal_count
      ? `${goals(planned)} planned.`
      : `${goals(planned)} planned, ${month.planned_goal_count} with an installment this month.`,
  ];

  if (!overview.is_total_complete) {
    lines.push("This total is incomplete: some Goals are not included (see below).");
  }

  return lines;
}

const INSUFFICIENT_REASONS = {
  unresolved_currency_data: (currency: string) =>
    `Some recorded income or expenses in these months have no amount in your base currency (${currency}), so no average is shown.`,
  fewer_than_two_active_months: () =>
    "A comparison needs at least 2 of the last 3 completed months with both recorded income and recorded expenses.",
} as const;

// How this month's installments compare with recorded history, or one sentence
// on why there is no comparison. Empty when no Goal is planned.
export function overviewComparisonLines(overview: GoalSavingsOverview): string[] {
  const { history, base_currency: currency } = overview;

  switch (history.status) {
    case "no_planned_goals":
      return [];
    case "insufficient_data": {
      const reasons = overview.limitations.flatMap((code) => {
        if (code === "unresolved_currency_data") {
          return [INSUFFICIENT_REASONS.unresolved_currency_data(currency)];
        }

        if (code === "fewer_than_two_active_months") {
          return [INSUFFICIENT_REASONS.fewer_than_two_active_months()];
        }

        return [];
      });

      return [reasons.length > 0 ? reasons.join(" ") : "There is not enough recorded history to compare yet."];
    }
    case "comparable": {
      const month = thisMonth(overview);
      const lines: string[] = [];

      if (history.average_monthly_net_flow !== null) {
        lines.push(
          `Your recorded monthly net flow averaged ${money(history.average_monthly_net_flow, currency)} over ${periodPhrase(history.months_used)}.`,
        );
      }

      if (month !== null && month.historical_difference !== null && month.difference_direction !== null) {
        const gap = money(withoutSign(month.historical_difference), currency);

        switch (month.difference_direction) {
          case "surplus":
            lines.push(`On that history, your average was ${gap} above this month's combined installment.`);
            break;
          case "shortfall":
            lines.push(`On that history, your average was ${gap} below this month's combined installment.`);
            break;
          case "equal":
            lines.push("On that history, your average matched this month's combined installment.");
            break;
          default: {
            const exhaustive: never = month.difference_direction;

            lines.push(String(exhaustive));
          }
        }
      }

      return lines;
    }
    default: {
      const exhaustive: never = history.status;

      return [String(exhaustive)];
    }
  }
}

// What is NOT in the total, from the backend's counts. Unplanned Goals are said
// to be unplanned, never to need nothing; other-currency Goals are said to be
// left out and never converted.
export function overviewNotices(overview: GoalSavingsOverview): string[] {
  const { no_target_date, target_date_passed, other_currency, other_currencies } = overview.exclusions;
  const notices: string[] = [];

  if (other_currency > 0) {
    notices.push(
      `${goals(other_currency)} in ${other_currencies.join(", ")} ${verb(other_currency, "is", "are")} not included, because amounts in different currencies are never added or converted. The total is incomplete.`,
    );
  }

  if (no_target_date > 0) {
    notices.push(
      `${goals(no_target_date)} ${verb(no_target_date, "has", "have")} no target date, so no installment is calculated. ${verb(no_target_date, "It is", "They are")} not counted as needing nothing.`,
    );
  }

  if (target_date_passed > 0) {
    notices.push(
      `${goals(target_date_passed)} ${verb(target_date_passed, "has", "have")} a target date that has passed, so no installment is calculated. Update ${verb(target_date_passed, "its date", "their dates")} to plan ahead.`,
    );
  }

  return notices;
}

export type OverviewRow = { label: string; value: string };

// This month's installment of each contributing Goal, in priority order.
export function overviewContributionRows(overview: GoalSavingsOverview): OverviewRow[] {
  const month = thisMonth(overview);

  if (month === null) {
    return [];
  }

  const names = new Map(overview.planned_goals.map((goal) => [goal.goal_id, goal.name] as const));

  return month.contributions.map((entry) => ({
    label: names.get(entry.goal_id) ?? "Goal",
    value: money(entry.amount, overview.base_currency),
  }));
}

// One row per month of the window: the combined installment, how many Goals it
// covers and, when the backend compared it, how recorded net flow stands.
// Consecutive months with no installment at all are shown as one range, so a
// Goal that ends early does not leave a long run of identical rows; every month
// of the window is still covered.
export function overviewMonthRows(overview: GoalSavingsOverview): OverviewRow[] {
  const rows: OverviewRow[] = [];
  let emptyRun: string[] = [];

  const flushEmptyRun = () => {
    if (emptyRun.length > 0) {
      const label = emptyRun.length === 1 ? emptyRun[0] : `${emptyRun[0]} to ${emptyRun[emptyRun.length - 1]}`;

      rows.push({ label, value: "no installments" });
      emptyRun = [];
    }
  };

  for (const month of overview.months) {
    const label = month.period_start.slice(0, 7);

    if (month.planned_goal_count === 0) {
      emptyRun.push(label);
      continue;
    }

    flushEmptyRun();

    const base = `${money(month.total_required, overview.base_currency)} for ${goals(month.planned_goal_count)}`;

    if (month.historical_difference === null || month.difference_direction === null) {
      rows.push({ label, value: base });
      continue;
    }

    const gap = money(withoutSign(month.historical_difference), overview.base_currency);
    const standing =
      month.difference_direction === "surplus"
        ? `recorded average ${gap} above`
        : month.difference_direction === "shortfall"
          ? `recorded average ${gap} below`
          : "recorded average matches";

    rows.push({ label, value: `${base} (${standing})` });
  }

  flushEmptyRun();

  return rows;
}

// Said once when some Goal keeps needing installments after the 12 months.
export function overviewContinuesNote(overview: GoalSavingsOverview): string | null {
  return overview.planned_goals.some((goal) => goal.continues_after_window)
    ? "Some Goals need installments after these 12 months."
    : null;
}
