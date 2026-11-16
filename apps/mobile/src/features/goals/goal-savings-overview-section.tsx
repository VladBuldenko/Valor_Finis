import { Text, View } from "react-native";
import type { UseQueryResult } from "@tanstack/react-query";

import { QueryBoundary } from "../../components/query-states";
import {
  OVERVIEW_ASSUMPTION,
  OVERVIEW_DISCLAIMER,
  OVERVIEW_NOT_MODELLED,
  OVERVIEW_TITLE,
  hasOverviewContent,
  overviewComparisonLines,
  overviewContinuesNote,
  overviewContributionRows,
  overviewHeadline,
  overviewMonthRows,
  overviewNotices,
  overviewSummaryLines,
} from "./goal-savings-overview-view";
import { styles } from "./goals.styles";
import type { GoalSavingsOverview } from "./goal.types";

// VF-GOALS-PLANNING-002B: the "Savings plans" overview at the top of the Goals
// list. Read-only and advisory. Every figure, count and choice of sentence comes
// from the backend's GET /goals/savings-overview (the query is owned by the
// screen so its pull-to-refresh re-reads it); nothing is calculated here and
// nothing is stored, scheduled or reserved. It has its own loading, error and
// Retry, so a failed overview never hides the Goals below it.
export function GoalSavingsOverviewSection({ query }: { query: UseQueryResult<GoalSavingsOverview> }) {
  // Nothing to plan (no Goals, or none that needs or lacks a plan): no section.
  if (query.data !== undefined && !hasOverviewContent(query.data)) {
    return null;
  }

  return (
    <View style={styles.card}>
      <Text style={styles.name} accessibilityRole="header">
        {OVERVIEW_TITLE}
      </Text>

      <QueryBoundary query={query} what="savings plans">
        {(overview) => {
          const headline = overviewHeadline(overview);
          const summary = overviewSummaryLines(overview);
          const continues = overviewContinuesNote(overview);

          return (
            <View>
              {headline ? (
                <View accessible accessibilityLabel={`${headline.label}: ${headline.amount}`}>
                  <Text style={styles.overviewText}>{headline.label}</Text>
                  <Text style={styles.amount}>{headline.amount}</Text>
                </View>
              ) : null}

              {summary.map((line) => (
                <Text key={line} style={styles.overviewText}>
                  {line}
                </Text>
              ))}

              {overviewComparisonLines(overview).map((line) => (
                <Text key={line} style={styles.overviewText}>
                  {line}
                </Text>
              ))}

              {overviewNotices(overview).map((notice) => (
                <Text key={notice} style={styles.overviewText}>
                  {notice}
                </Text>
              ))}

              {overview.planned_goals.length > 0 ? (
                <View>
                  <Text style={styles.overviewLabel} accessibilityRole="header">
                    This month, by Goal
                  </Text>
                  {overviewContributionRows(overview).map((row) => (
                    <Text
                      key={row.label}
                      style={styles.overviewText}
                      accessibilityLabel={`${row.label}: ${row.value}`}
                    >
                      {row.label}: {row.value}
                    </Text>
                  ))}

                  <Text style={styles.overviewLabel} accessibilityRole="header">
                    Next {overview.horizon_months} months
                  </Text>
                  {overviewMonthRows(overview).map((row) => (
                    <Text
                      key={row.label}
                      style={styles.overviewHelperText}
                      accessibilityLabel={`${row.label}: ${row.value}`}
                    >
                      {row.label}: {row.value}
                    </Text>
                  ))}
                  {continues ? <Text style={styles.overviewHelperText}>{continues}</Text> : null}
                </View>
              ) : null}

              <Text style={styles.overviewHelperText}>{OVERVIEW_ASSUMPTION}</Text>
              <Text style={styles.overviewHelperText}>{OVERVIEW_NOT_MODELLED}</Text>
              <Text style={styles.overviewHelperText}>{OVERVIEW_DISCLAIMER}</Text>
            </View>
          );
        }}
      </QueryBoundary>
    </View>
  );
}
