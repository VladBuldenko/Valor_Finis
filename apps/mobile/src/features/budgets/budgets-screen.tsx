import { useQuery } from "@tanstack/react-query";
import {
  ActivityIndicator,
  SafeAreaView,
  ScrollView,
  Text,
  View,
} from "react-native";

import { getBudgetStatus } from "../analytics/analytics.service";
import type { BudgetStatusItem } from "../analytics/analytics.types";
import { useAuth } from "../auth/auth-context";
import { getBudgets } from "./budget.service";
import { styles } from "./budgets.styles";

// Capitalizes the backend's lowercase period literal ("monthly") for display.
// This is presentation-only text formatting, not a financial calculation.
function formatPeriod(period: string): string {
  return period.charAt(0).toUpperCase() + period.slice(1);
}

function formatDateRange(startDate: string, endDate: string | null): string {
  return endDate ? `${startDate} – ${endDate}` : `${startDate} – Ongoing`;
}

export function BudgetsScreen() {
  const { session } = useAuth();

  const {
    data: budgets = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["budgets", session?.user.id],
    queryFn: getBudgets,
    enabled: Boolean(session),
  });

  // Reuses the same query key the dashboard uses for budget status, so the
  // two screens share one cached fetch instead of issuing duplicate requests.
  const {
    data: budgetStatus = [],
    error: budgetStatusError,
  } = useQuery({
    queryKey: ["analytics", "budget-status", session?.user.id],
    queryFn: getBudgetStatus,
    enabled: Boolean(session),
  });

  // budget_id on BudgetStatusItem is the verified, reliable join key back to
  // a budget's own id -- the analytics service computes exactly one status
  // item per budget owned by the user (see analytics_service.get_budget_status).
  const budgetStatusById = new Map<string, BudgetStatusItem>(
    budgetStatus.map((status) => [status.budget_id, status]),
  );

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title}>Budgets</Text>

        {budgetStatusError ? (
          <Text style={styles.noticeText}>
            Spending progress is unavailable right now.
          </Text>
        ) : null}

        {isLoading ? (
          <ActivityIndicator style={styles.loader} />
        ) : error ? (
          <Text style={styles.errorText}>Unable to load budgets.</Text>
        ) : budgets.length === 0 ? (
          <Text style={styles.secondaryText}>No budgets yet.</Text>
        ) : (
          <View style={styles.list}>
            {budgets.map((budget) => {
              const status = budgetStatusById.get(budget.id);

              const categoryLabel = status
                ? status.category_name
                : budget.category_id === null
                  ? "General budget"
                  : "Category budget";

              return (
                <View key={budget.id} style={styles.card}>
                  <Text style={styles.name}>{budget.name}</Text>

                  <Text style={styles.secondaryText}>{categoryLabel}</Text>

                  <Text style={styles.secondaryText}>
                    {formatPeriod(budget.period)} ·{" "}
                    {formatDateRange(budget.start_date, budget.end_date)}
                  </Text>

                  <Text style={styles.amount}>
                    {budget.limit_amount} {budget.currency}
                  </Text>

                  {status ? (
                    <>
                      <Text style={styles.secondaryText}>
                        Spent: {status.spent} {budget.currency}
                      </Text>

                      <Text
                        style={
                          status.is_exceeded
                            ? styles.exceededText
                            : styles.secondaryText
                        }
                      >
                        {status.is_exceeded
                          ? `Exceeded by ${status.exceeded_amount} ${budget.currency}`
                          : `Remaining ${status.remaining} ${budget.currency}`}
                      </Text>
                    </>
                  ) : null}
                </View>
              );
            })}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
