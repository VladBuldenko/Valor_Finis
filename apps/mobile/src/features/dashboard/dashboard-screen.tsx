import { useState } from "react";
import { Link } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  RefreshControl,
  SafeAreaView,
  ScrollView,
  Text,
  View,
} from "react-native";

import { InlineError, QueryBoundary } from "../../components/query-states";
import { refetcherOf, useScreenRefresh } from "../../lib/screen-refresh";
import {
  getBudgetStatus,
  getCategorySummary,
  getFinancialOverview,
  getGoalProgress,
  getMonthlySummary,
} from "../analytics/analytics.service";
import type {
  BudgetStatusItem,
  GoalProgressItem,
} from "../analytics/analytics.types";
import {
  formatNetFlow,
  formatOverviewPeriodNote,
} from "../analytics/financial-overview-presentation";
import { useLocalCalendarMonth } from "../analytics/use-local-calendar-month";
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
import { inboxIndicatorPresentation } from "../financial-rules/inbox-data";
import { useInboxData } from "../financial-rules/use-inbox-data";
import { getGoals } from "../goals/goal.service";
import { styles } from "./dashboard.styles";
import { getAuthErrorMessage } from "../../api/user-facing-error";

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
  // The same shared Inbox data the Inbox screen reads (one derivation).
  const inbox = useInboxData();
  const inboxPresentation = inboxIndicatorPresentation(inbox.indicator);

  // The device's local calendar month, re-read whenever the Dashboard
  // regains focus (VF-019C), so returning to it after a month boundary
  // moves every month-scoped card below to the new month.
  const { year, month } = useLocalCalendarMonth();

  // Locale-safe label for the period the monthly/category summary and
  // income/expenses cards are scoped to (e.g. "September 2026"). This only
  // clarifies what is already displayed.
  const periodLabel = new Date(year, month - 1, 1).toLocaleDateString(
    "en-US",
    { month: "long", year: "numeric" },
  );

  const summaryQuery = useQuery({
    queryKey: ["analytics", "monthly-summary", session?.user.id, year, month],
    queryFn: () => getMonthlySummary(year, month),
    enabled: Boolean(session),
  });

  // Financial Overview for the same local month (VF-019C). Independent of
  // monthly-summary above: that card counts the whole calendar month,
  // including future-dated Expenses, while this one counts records through
  // the server's current date -- so their expense figures may legitimately
  // differ, and neither replaces the other.
  const financialOverviewQuery = useQuery({
    queryKey: ["analytics", "financial-overview", session?.user.id, year, month],
    queryFn: () => getFinancialOverview(year, month),
    enabled: Boolean(session),
  });

  const categorySummaryQuery = useQuery({
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
  const categorySummary = categorySummaryQuery.data ?? [];

  const budgetStatusQuery = useQuery({
    queryKey: ["analytics", "budget-status", session?.user.id],
    queryFn: getBudgetStatus,
    enabled: Boolean(session),
  });
  const budgetStatus = budgetStatusQuery.data ?? [];

  // Secondary, supplementary data used only to resolve Budget Status
  // currency -- the Budget Status card's own loading/error state stays
  // driven by budgetStatus above, and a failure here surfaces as a small
  // non-blocking notice instead of replacing the whole card.
  const budgetsQuery = useQuery({
    queryKey: ["budgets", session?.user.id],
    queryFn: getBudgets,
    enabled: Boolean(session),
  });
  const budgets = budgetsQuery.data ?? [];

  const budgetsById = new Map<string, Budget>(
    budgets.map((budget) => [budget.id, budget]),
  );

  // Goals are the authoritative source for id/currency/target_amount/
  // current_amount -- mirrors goals-screen.tsx, where the Goal list (not
  // goal-progress) drives what renders.
  const goalsQuery = useQuery({
    queryKey: ["goals", session?.user.id],
    queryFn: getGoals,
    enabled: Boolean(session),
  });
  const goals = goalsQuery.data ?? [];

  // Supplementary: Remaining/Progress rows only. A failure here must not
  // blank the Goal list -- it surfaces as a small non-blocking notice,
  // same as goalProgressError on goals-screen.tsx.
  const goalProgressQuery = useQuery({
    queryKey: ["analytics", "goal-progress", session?.user.id],
    queryFn: getGoalProgress,
    enabled: Boolean(session),
  });
  const goalProgress = goalProgressQuery.data ?? [];
  const refresh = useScreenRefresh(() => [
    refetcherOf(summaryQuery),
    refetcherOf(financialOverviewQuery),
    refetcherOf(categorySummaryQuery),
    refetcherOf(budgetStatusQuery),
    refetcherOf(budgetsQuery),
    refetcherOf(goalsQuery),
    refetcherOf(goalProgressQuery),
    // The Inbox entry's sources (GET only; the indicator logic is unchanged).
    refetcherOf(inbox.proposals),
    refetcherOf(inbox.alerts),
  ]);

  // goal_id is the join key back to Goal.id -- never join by name, never
  // assume array order matches (mirrors goals-screen.tsx / budgetsById above).
  const goalProgressById = new Map<string, GoalProgressItem>(
    goalProgress.map((progress) => [progress.goal_id, progress]),
  );

  // Archived goals are historical records (VF-016F2) -- the Dashboard's
  // Goal progress card is meant to surface what still needs attention, so
  // it only ever shows non-archived goals. "Current" deliberately includes
  // both "active" and "completed", not just "active": completed is a
  // valid, still-relevant status and must not disappear from this card.
  // Visibility is driven by Goal.status only -- never inferred from
  // balance/target/progress/dates.
  const currentGoals = goals.filter((goal) => goal.status !== "archived");

  async function handleSignOut() {
    try {
      setIsSigningOut(true);

      await signOut();
    } catch (error) {
      const message = getAuthErrorMessage(error, "Unable to sign out.");

      Alert.alert("Sign out failed", message);
    } finally {
      setIsSigningOut(false);
    }
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refresh.refreshing} onRefresh={refresh.onRefresh} />}
      >
        <Text style={styles.title}>Valor Finis</Text>

        <Text style={styles.subtitle}>Dashboard</Text>

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>This month</Text>

          <Text style={styles.secondaryText}>{periodLabel}</Text>

          <QueryBoundary query={summaryQuery} what="monthly summary" isEmpty={() => false}>
            {(monthlySummary) => (
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
            )}
          </QueryBoundary>
        </View>

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Income and expenses</Text>

          <Text style={styles.secondaryText}>{periodLabel}</Text>

          <QueryBoundary query={financialOverviewQuery} what="income and expenses" isEmpty={() => false}>
            {(financialOverview) => (
            <>
              <Text style={styles.secondaryText}>
                {formatOverviewPeriodNote(financialOverview)}
              </Text>

              {financialOverview.data_status === "incomplete_data" ? (
                <Text style={styles.noticeText}>
                  Incomplete data: some records could not be counted in{" "}
                  {financialOverview.base_currency} and are not included in
                  these totals.
                </Text>
              ) : null}

              {/* Backend figures rendered as returned -- Net is never
                  recomputed here. */}
              <View style={styles.categoryList}>
                <View style={styles.categoryRow}>
                  <Text style={styles.categoryName}>Income</Text>
                  <Text style={styles.categoryAmount}>
                    {formatAmount(
                      financialOverview.income_total,
                      financialOverview.base_currency,
                    )}
                  </Text>
                </View>

                <View style={styles.categoryRow}>
                  <Text style={styles.categoryName}>Expenses</Text>
                  <Text style={styles.categoryAmount}>
                    {formatAmount(
                      financialOverview.expense_total,
                      financialOverview.base_currency,
                    )}
                  </Text>
                </View>

                <View style={styles.categoryRow}>
                  <View style={styles.categoryDetails}>
                    <Text style={styles.categoryName}>
                      Net (Income - Expenses)
                    </Text>
                  </View>
                  <Text style={styles.categoryAmount}>
                    {formatNetFlow(
                      financialOverview.net_flow,
                      financialOverview.base_currency,
                    )}
                  </Text>
                </View>
              </View>
            </>
            )}
          </QueryBoundary>

          <Link href="/overview" asChild>
            <Pressable accessibilityRole="button" style={styles.button}>
              <Text style={styles.buttonText}>Financial Overview</Text>
            </Pressable>
          </Link>
        </View>

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Spending by category</Text>

          <QueryBoundary
            query={categorySummaryQuery}
            what="category spending"
            empty="No spending by category this month."
          >
            {() => (
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
          </QueryBoundary>
        </View>

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Budget status</Text>

          {budgetsQuery.isError && budgetsQuery.data === undefined ? (
            <InlineError
              what="budget currency details"
              error={budgetsQuery.error}
              kind="partial"
              retrying={budgetsQuery.isFetching}
              onRetry={() => void budgetsQuery.refetch()}
            />
          ) : null}

          <QueryBoundary query={budgetStatusQuery} what="budget status" empty="No budgets yet.">
            {() => (
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
          </QueryBoundary>
        </View>

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Goal progress</Text>

          {goalProgressQuery.isError && goalProgressQuery.data === undefined ? (
            <InlineError
              what="goal progress"
              error={goalProgressQuery.error}
              kind="partial"
              retrying={goalProgressQuery.isFetching}
              onRetry={() => void goalProgressQuery.refetch()}
            />
          ) : null}

          <QueryBoundary
            query={goalsQuery}
            what="goals"
            isEmpty={() => currentGoals.length === 0}
            empty={goals.length === 0 ? "No goals yet." : "No current goals."}
          >
            {() => (
            <View style={styles.categoryList}>
              {currentGoals.map((goal) => {
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
          </QueryBoundary>
        </View>

        {/* Navigation only (VF-017F) -- Accounts data is never fetched or
            aggregated on this screen; see accounts-screen.tsx for the
            actual Account list. */}
        <Link href="/accounts" asChild>
          <Pressable style={styles.button}>
            <Text style={styles.buttonText}>Accounts</Text>
          </Pressable>
        </Link>

        {/* Navigation only (VF-017G) -- Income is never fetched or
            totaled on this screen; see income-screen.tsx. */}
        <Link href="/income" asChild>
          <Pressable style={styles.button}>
            <Text style={styles.buttonText}>Income</Text>
          </Pressable>
        </Link>

        {/* Navigation only (VF-018E) -- Transfers are never fetched or
            aggregated on this screen; see transfers-screen.tsx. */}
        <Link href="/transfers" asChild>
          <Pressable style={styles.button}>
            <Text style={styles.buttonText}>Transfers</Text>
          </Pressable>
        </Link>

        <Link href="/expenses" asChild>
          <Pressable style={styles.button}>
            <Text style={styles.buttonText}>Expenses</Text>
          </Pressable>
        </Link>

        <Link href="/analytics" asChild>
          <Pressable style={styles.button}>
            <Text style={styles.buttonText}>Analytics</Text>
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

        <Link href="/inbox" asChild>
          <Pressable
            style={styles.button}
            accessibilityRole="button"
            accessibilityLabel={inboxPresentation.accessibilityLabel}
          >
            <Text style={styles.buttonText}>Inbox</Text>
            <Text style={styles.buttonText}>{inboxPresentation.marker}</Text>
          </Pressable>
        </Link>

        <Link href="/rules" asChild>
          <Pressable style={styles.button}>
            <Text style={styles.buttonText}>Rules</Text>
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
