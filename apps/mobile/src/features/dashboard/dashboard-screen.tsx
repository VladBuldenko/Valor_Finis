import { useState } from "react";
import { Link } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  SafeAreaView,
  ScrollView,
  Text,
  View,
} from "react-native";

import {
  getBudgetStatus,
  getCategorySummary,
  getGoalProgress,
  getMonthlySummary,
} from "../analytics/analytics.service";
import type {
  BudgetStatusItem,
  GoalProgressItem,
} from "../analytics/analytics.types";
import { useAuth } from "../auth/auth-context";
import { signOut } from "../auth/auth.service";
import {
  formatAmount,
  formatPeriodStateLabel,
  formatRiskLabel,
  formatUnresolvedNotice,
} from "../budgets/budget-status-presentation";
import { getBudgets } from "../budgets/budget.service";
import type { Budget } from "../budgets/budget.types";
import { getGoals } from "../goals/goal.service";
import { styles } from "./dashboard.styles";

// "1 expenses" reads wrong -- singularize only for exactly one.
function formatExpenseCount(count: number): string {
  return `${count} ${count === 1 ? "expense" : "expenses"}`;
}

// Budget Status doesn't carry currency directly -- it is resolved by joining
// BudgetStatusItem.budget_id back to the matching Budget entity's currency
// field. If no matching Budget is found (e.g. the budgets list failed to
// load, or hasn't caught up with a just-deleted budget), the amount is shown
// without a currency unit rather than guessing one.
function formatBudgetAmount(
  amount: string,
  currency: string | undefined,
): string {
  return currency ? formatAmount(amount, currency) : amount;
}

// Bolds risk text for the two states that need attention, without relying
// on color alone (VF-014B6, Section 7) -- a text label is always shown
// regardless of style.
function riskTextStyle(riskStatus: BudgetStatusItem["risk_status"]) {
  return riskStatus === "at_risk" || riskStatus === "exceeded"
    ? styles.exceededText
    : styles.secondaryText;
}

export function DashboardScreen() {
  const { session } = useAuth();
  const [isSigningOut, setIsSigningOut] = useState(false);

  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth() + 1;

  // Locale-safe label for the period the monthly/category summary cards are
  // scoped to (e.g. "September 2026"). This only clarifies what is already
  // displayed -- it does not refresh the period while the screen stays
  // mounted across a month boundary.
  const periodLabel = new Date(year, month - 1, 1).toLocaleDateString(
    "en-US",
    { month: "long", year: "numeric" },
  );

  const {
    data: monthlySummary,
    isLoading: isSummaryLoading,
    error: summaryError,
  } = useQuery({
    queryKey: ["analytics", "monthly-summary", session?.user.id, year, month],
    queryFn: () => getMonthlySummary(year, month),
    enabled: Boolean(session),
  });

  const {
    data: categorySummary = [],
    isLoading: isCategorySummaryLoading,
    error: categorySummaryError,
  } = useQuery({
    queryKey: [
      "analytics",
      "category-summary",
      session?.user.id,
      year,
      month,
    ],
    queryFn: () => getCategorySummary(year, month),
    enabled: Boolean(session),
  });

  const {
    data: budgetStatus = [],
    isLoading: isBudgetStatusLoading,
    error: budgetStatusError,
  } = useQuery({
    queryKey: ["analytics", "budget-status", session?.user.id],
    queryFn: getBudgetStatus,
    enabled: Boolean(session),
  });

  // Secondary, supplementary data used only to resolve Budget Status
  // currency -- the Budget Status card's own loading/error state stays
  // driven by budgetStatus above, and a failure here surfaces as a small
  // non-blocking notice instead of replacing the whole card.
  const { data: budgets = [], error: budgetsError } = useQuery({
    queryKey: ["budgets", session?.user.id],
    queryFn: getBudgets,
    enabled: Boolean(session),
  });

  const budgetsById = new Map<string, Budget>(
    budgets.map((budget) => [budget.id, budget]),
  );

  // Goals are the authoritative source for id/currency/target_amount/
  // current_amount -- mirrors goals-screen.tsx, where the Goal list (not
  // goal-progress) drives what renders.
  const {
    data: goals = [],
    isLoading: isGoalsLoading,
    error: goalsError,
  } = useQuery({
    queryKey: ["goals", session?.user.id],
    queryFn: getGoals,
    enabled: Boolean(session),
  });

  // Supplementary: Remaining/Progress rows only. A failure here must not
  // blank the Goal list -- it surfaces as a small non-blocking notice,
  // same as goalProgressError on goals-screen.tsx.
  const { data: goalProgress = [], error: goalProgressError } = useQuery({
    queryKey: ["analytics", "goal-progress", session?.user.id],
    queryFn: getGoalProgress,
    enabled: Boolean(session),
  });

  // goal_id is the join key back to Goal.id -- never join by name, never
  // assume array order matches (mirrors goals-screen.tsx / budgetsById above).
  const goalProgressById = new Map<string, GoalProgressItem>(
    goalProgress.map((progress) => [progress.goal_id, progress]),
  );

  async function handleSignOut() {
    try {
      setIsSigningOut(true);

      await signOut();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unable to sign out.";

      Alert.alert("Sign out failed", message);
    } finally {
      setIsSigningOut(false);
    }
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title}>Valor Finis</Text>

        <Text style={styles.subtitle}>Dashboard</Text>

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>This month</Text>

          <Text style={styles.secondaryText}>{periodLabel}</Text>

          {isSummaryLoading ? (
            <ActivityIndicator style={styles.loader} />
          ) : summaryError ? (
            <Text style={styles.errorText}>
              Unable to load monthly summary.
            </Text>
          ) : monthlySummary ? (
            <>
              <Text style={styles.amount}>
                {formatAmount(
                  monthlySummary.total_spent,
                  monthlySummary.base_currency,
                )}
              </Text>

              <Text style={styles.secondaryText}>
                {formatExpenseCount(monthlySummary.expenses_count)}
              </Text>

              {monthlySummary.unresolved_expenses_count > 0 ? (
                <Text style={styles.noticeText}>
                  {formatUnresolvedNotice(
                    monthlySummary.unresolved_expenses_count,
                  )}
                </Text>
              ) : null}
            </>
          ) : null}
        </View>

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Spending by category</Text>

          {isCategorySummaryLoading ? (
            <ActivityIndicator style={styles.loader} />
          ) : categorySummaryError ? (
            <Text style={styles.errorText}>
              Unable to load category spending.
            </Text>
          ) : categorySummary.length === 0 ? (
            <Text style={styles.secondaryText}>
              No spending by category this month.
            </Text>
          ) : (
            <View style={styles.categoryList}>
              {categorySummary.map((category) => (
                <View
                  key={category.category_id ?? "uncategorized"}
                  style={styles.categoryRow}
                >
                  <View style={styles.categoryDetails}>
                    <Text style={styles.categoryName}>
                      {category.category_name}
                    </Text>

                    <Text style={styles.secondaryText}>
                      {formatExpenseCount(category.expenses_count)}
                    </Text>

                    {category.unresolved_expenses_count > 0 ? (
                      <Text style={styles.noticeText}>
                        {category.unresolved_expenses_count} unresolved
                      </Text>
                    ) : null}
                  </View>

                  <Text style={styles.categoryAmount}>
                    {formatAmount(
                      category.total_spent,
                      category.base_currency,
                    )}
                  </Text>
                </View>
              ))}
            </View>
          )}
        </View>

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Budget status</Text>

          {budgetsError ? (
            <Text style={styles.noticeText}>
              Budget currency details are unavailable right now.
            </Text>
          ) : null}

          {isBudgetStatusLoading ? (
            <ActivityIndicator style={styles.loader} />
          ) : budgetStatusError ? (
            <Text style={styles.errorText}>
              Unable to load budget status.
            </Text>
          ) : budgetStatus.length === 0 ? (
            <Text style={styles.secondaryText}>No budgets yet.</Text>
          ) : (
            <View style={styles.categoryList}>
              {budgetStatus.map((budget) => {
                const currency = budgetsById.get(budget.budget_id)?.currency;
                const isNotStarted = budget.period_state === "not_started";
                const isActive = budget.period_state === "active";

                return (
                  <View key={budget.budget_id} style={styles.categoryRow}>
                    <View style={styles.categoryDetails}>
                      <Text style={styles.categoryName}>
                        {budget.budget_name}
                      </Text>

                      <Text style={styles.secondaryText}>
                        {budget.category_name}
                      </Text>

                      {!isActive ? (
                        <Text style={styles.secondaryText}>
                          {formatPeriodStateLabel(budget.period_state)}
                        </Text>
                      ) : null}

                      {isNotStarted ? (
                        <Text style={styles.secondaryText}>
                          Limit {formatBudgetAmount(
                            budget.limit_amount,
                            currency,
                          )}
                        </Text>
                      ) : (
                        <>
                          <Text style={styles.secondaryText}>
                            Spent: {formatBudgetAmount(budget.spent, currency)}{" "}
                            / {formatBudgetAmount(budget.limit_amount, currency)}
                          </Text>

                          <Text
                            style={
                              budget.is_exceeded
                                ? styles.exceededText
                                : styles.secondaryText
                            }
                          >
                            {budget.is_exceeded
                              ? `Exceeded by ${formatBudgetAmount(
                                  budget.exceeded_amount,
                                  currency,
                                )}`
                              : `Remaining ${formatBudgetAmount(
                                  budget.remaining,
                                  currency,
                                )}`}
                          </Text>

                          <Text style={riskTextStyle(budget.risk_status)}>
                            Risk: {formatRiskLabel(budget.risk_status)}
                          </Text>

                          {isActive ? (
                            <Text style={styles.secondaryText}>
                              Daily allowance:{" "}
                              {formatBudgetAmount(
                                budget.daily_spending_allowance,
                                currency,
                              )}
                            </Text>
                          ) : null}

                          {budget.projected_spending !== null ? (
                            <Text style={styles.secondaryText}>
                              Projected:{" "}
                              {formatBudgetAmount(
                                budget.projected_spending,
                                currency,
                              )}
                            </Text>
                          ) : null}
                        </>
                      )}
                    </View>
                  </View>
                );
              })}
            </View>
          )}
        </View>

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Goal progress</Text>

          {goalProgressError ? (
            <Text style={styles.noticeText}>
              Goal progress is temporarily unavailable.
            </Text>
          ) : null}

          {isGoalsLoading ? (
            <ActivityIndicator style={styles.loader} />
          ) : goalsError ? (
            <Text style={styles.errorText}>Unable to load goals.</Text>
          ) : goals.length === 0 ? (
            <Text style={styles.secondaryText}>No goals yet.</Text>
          ) : (
            <View style={styles.categoryList}>
              {goals.map((goal) => {
                const progress = goalProgressById.get(goal.id);

                return (
                  <View key={goal.id} style={styles.categoryRow}>
                    <View style={styles.categoryDetails}>
                      <Text style={styles.categoryName}>{goal.name}</Text>

                      <Text style={styles.secondaryText}>
                        Saved: {goal.current_amount} / {goal.target_amount}{" "}
                        {goal.currency}
                      </Text>

                      {progress ? (
                        <>
                          <Text style={styles.secondaryText}>
                            Remaining: {progress.remaining_amount}{" "}
                            {goal.currency}
                          </Text>

                          <Text style={styles.secondaryText}>
                            Progress: {progress.progress_percent}%
                          </Text>
                        </>
                      ) : null}
                    </View>
                  </View>
                );
              })}
            </View>
          )}
        </View>

        <Link href="/expenses" asChild>
          <Pressable style={styles.button}>
            <Text style={styles.buttonText}>Expenses</Text>
          </Pressable>
        </Link>

        <Link href="/budgets" asChild>
          <Pressable style={styles.button}>
            <Text style={styles.buttonText}>Budgets</Text>
          </Pressable>
        </Link>

        <Link href="/categories" asChild>
          <Pressable style={styles.button}>
            <Text style={styles.buttonText}>Categories</Text>
          </Pressable>
        </Link>

        <Link href="/goals" asChild>
          <Pressable style={styles.button}>
            <Text style={styles.buttonText}>Goals</Text>
          </Pressable>
        </Link>

        <Link href="/receipts/upload" asChild>
          <Pressable style={styles.button}>
            <Text style={styles.buttonText}>Scan receipt</Text>
          </Pressable>
        </Link>

        <Pressable
          disabled={isSigningOut}
          onPress={handleSignOut}
          style={styles.button}
        >
          {isSigningOut ? (
            <ActivityIndicator />
          ) : (
            <Text style={styles.buttonText}>Log out</Text>
          )}
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}
