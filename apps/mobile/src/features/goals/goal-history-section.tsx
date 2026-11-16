import { Text, View } from "react-native";
import type { UseQueryResult } from "@tanstack/react-query";

import { QueryBoundary } from "../../components/query-states";
import {
  HISTORY_DISCLAIMER,
  HISTORY_NOT_MODELLED,
  HISTORY_TITLE,
  historyMonthRows,
  historySentences,
} from "./goal-history-view";
import { styles } from "./goals.styles";
import type { GoalHistoryComparison } from "./goal.types";

// VF-GOALS-PLANNING-002A: "Compared with your financial history", shown inside
// the Goal plan section. Read-only and advisory. Every figure and every choice
// of sentence comes from the backend's GET /goals/{id}/plan/history-comparison
// (the query is owned by useGoalPlan so the screen's pull-to-refresh can
// re-read it); nothing is calculated here and nothing is stored or reserved.
export function GoalHistorySection({ query }: { query: UseQueryResult<GoalHistoryComparison> }) {
  return (
    <View style={styles.formGroup}>
      <Text style={styles.label} accessibilityRole="header">
        {HISTORY_TITLE}
      </Text>

      <QueryBoundary query={query} what="financial history comparison">
        {(comparison) => (
          <View>
            {historySentences(comparison).map((sentence) => (
              <Text key={sentence} style={styles.secondaryText}>
                {sentence}
              </Text>
            ))}

            {historyMonthRows(comparison).map((row) => (
              <Text key={row.label} style={styles.helperText} accessibilityLabel={`${row.label}: ${row.value}`}>
                {row.label}: {row.value}
              </Text>
            ))}

            <Text style={styles.helperText}>{HISTORY_NOT_MODELLED}</Text>
            <Text style={styles.helperText}>{HISTORY_DISCLAIMER}</Text>
          </View>
        )}
      </QueryBoundary>
    </View>
  );
}
