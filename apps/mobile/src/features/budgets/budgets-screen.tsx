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
import {
  formatAmount,
  formatPercent,
  formatPeriodLabel,
  formatPeriodStateLabel,
  formatRiskLabel,
} from "./budget-status-presentation";
import { deleteBudget, getBudgets } from "./budget.service";
import { styles } from "./budgets.styles";
import type { Budget } from "./budget.types";

function formatDateRange(startDate: string, endDate: string | null): string {
  return endDate ? `${startDate} – ${endDate}` : `${startDate} – Ongoing`;
}

// A backend Decimal-string amount, compared only against the literal
// zero-quantized form the backend always emits for these two fields
// (both are `max(x, Decimal("0")).quantize(Decimal("0.01"))`, so a zero
// value is always exactly "0.00"). This decides which of two already-
// computed backend fields to display, per Section 10 - it is not a
// recalculation of either value.
function isPositiveAmount(value: string): boolean {
  return value !== "0.00";
}

// Full status presentation for one Budget with a resolved BudgetStatusItem,
// branched by lifecycle state (VF-014B6, Section 5). Every number/label
// here comes directly from the backend - nothing is recomputed. Kept as
// its own component so BudgetsScreen's list body stays readable.
function BudgetStatusDetails({
  status,
  currency,
}: {
  status: BudgetStatusItem;
  currency: string;
}) {
  const isActive = status.period_state === "active";
  const isEnded = status.period_state === "ended";
  const isNotStarted = status.period_state === "not_started";

  return (
    <View style={styles.statusSection}>
      <View style={styles.badgeRow}>
        <Text style={styles.stateBadgeText}>
          {formatPeriodStateLabel(status.period_state)}
        </Text>

        {status.is_partial_period ? (
          <Text style={styles.partialBadgeText}>Partial period</Text>
        ) : null}
      </View>

      <Text style={styles.secondaryText}>
        Current period: {status.effective_start} – {status.effective_end}
      </Text>

      <Text style={styles.amount}>
        {formatAmount(status.limit_amount, currency)}
      </Text>

      {isNotStarted ? (
        <>
          <Text style={styles.secondaryText}>
            Planned allowance: {formatAmount(status.daily_spending_allowance, currency)}{" "}
            per day once this budget starts
          </Text>

          <Text style={styles.noticeText}>
            Projection available after spending begins.
          </Text>
        </>
      ) : (
        <>
          <Text style={styles.secondaryText}>
            Spent: {formatAmount(status.spent, currency)}
          </Text>

          <Text
            style={
              status.is_exceeded ? styles.exceededText : styles.secondaryText
            }
          >
            {status.is_exceeded
              ? `Exceeded by ${formatAmount(status.exceeded_amount, currency)}`
              : `Remaining ${formatAmount(status.remaining, currency)}`}
          </Text>

          <Text style={styles.secondaryText}>
            Utilization: {formatPercent(status.utilization_percent)}
          </Text>

          <Text style={styles.secondaryText}>
            Risk: {formatRiskLabel(status.risk_status)}
          </Text>

          {isActive ? (
            <>
              <Text style={styles.secondaryText}>
                {status.days_remaining}{" "}
                {status.days_remaining === 1 ? "day" : "days"} remaining
              </Text>

              <Text style={styles.secondaryText}>
                Available per remaining day:{" "}
                {formatAmount(status.daily_spending_allowance, currency)}
              </Text>
            </>
          ) : null}

          {status.projected_spending !== null ? (
            <>
              <Text style={styles.secondaryText}>
                {isEnded ? "Final spend" : "Projected spending"}:{" "}
                {formatAmount(status.projected_spending, currency)}
              </Text>

              {status.projected_deficit !== null &&
              isPositiveAmount(status.projected_deficit) ? (
                <Text style={styles.exceededText}>
                  {isEnded
                    ? "Ended over budget by"
                    : "Projected to exceed by"}{" "}
                  {formatAmount(status.projected_deficit, currency)}
                </Text>
              ) : status.projected_surplus !== null &&
                isPositiveAmount(status.projected_surplus) ? (
                <Text style={styles.secondaryText}>
                  {isEnded ? "Ended under budget by" : "Projected surplus"}{" "}
                  {formatAmount(status.projected_surplus, currency)}
                </Text>
              ) : null}
            </>
          ) : null}
        </>
      )}
    </View>
  );
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
                    {formatPeriodLabel(budget.period)} · {budget.currency}
                  </Text>

                  <Text style={styles.secondaryText}>
                    Runs: {formatDateRange(budget.start_date, budget.end_date)}
                  </Text>

                  {status ? (
                    <BudgetStatusDetails
                      status={status}
                      currency={budget.currency}
                    />
                  ) : (
                    <Text style={styles.amount}>
                      {formatAmount(budget.limit_amount, budget.currency)}
                    </Text>
                  )}

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
