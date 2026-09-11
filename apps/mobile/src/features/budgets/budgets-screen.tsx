import { Link } from "expo-router";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  SafeAreaView,
  ScrollView,
  Text,
  View,
} from "react-native";

import { getBudgetStatus } from "../analytics/analytics.service";
import type { BudgetStatusItem } from "../analytics/analytics.types";
import { useAuth } from "../auth/auth-context";
import { deleteBudget, getBudgets } from "./budget.service";
import { styles } from "./budgets.styles";
import type { Budget } from "./budget.types";

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
  const queryClient = useQueryClient();

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

  const deleteBudgetMutation = useMutation({
    mutationFn: (budgetId: string) => deleteBudget(budgetId),

    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["budgets", session?.user.id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["analytics", "budget-status", session?.user.id],
        }),
      ]);
    },

    onError: (mutationError) => {
      const message =
        mutationError instanceof Error
          ? mutationError.message
          : "Unable to delete budget.";

      Alert.alert("Delete budget failed", message);
    },
  });

  function handleDeleteBudget(budget: Budget) {
    // Guards against a double tap firing a second DELETE while the first
    // one is still in flight -- mirrors expense-detail-screen.tsx's
    // isMutating guard.
    if (deleteBudgetMutation.isPending) {
      return;
    }

    Alert.alert(
      "Delete budget?",
      `"${budget.name}" will be permanently deleted.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: () => deleteBudgetMutation.mutate(budget.id),
        },
      ],
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title}>Budgets</Text>

        <Link href="/budgets/new" asChild>
          <Pressable style={styles.button}>
            <Text style={styles.buttonText}>Add Budget</Text>
          </Pressable>
        </Link>

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

                  <Link
                    href={{
                      pathname: "/budgets/[id]/edit",
                      params: { id: budget.id },
                    }}
                    asChild
                  >
                    <Pressable style={styles.editButton}>
                      <Text style={styles.editButtonText}>Edit budget</Text>
                    </Pressable>
                  </Link>

                  <Pressable
                    style={styles.deleteButton}
                    disabled={deleteBudgetMutation.isPending}
                    onPress={() => handleDeleteBudget(budget)}
                  >
                    {deleteBudgetMutation.isPending &&
                    deleteBudgetMutation.variables === budget.id ? (
                      <ActivityIndicator size="small" />
                    ) : (
                      <Text style={styles.deleteButtonText}>
                        Delete budget
                      </Text>
                    )}
                  </Pressable>
                </View>
              );
            })}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
