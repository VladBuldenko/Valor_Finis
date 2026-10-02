import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useAuth } from "../auth/auth-context";
import { formatAmount } from "./analytics-presentation";
import { getFinancialOverview, getIncomeExpenseTrend } from "./analytics.service";
import type { FinancialFlowFigures } from "./analytics.types";
import {
  compareCalendarMonths,
  formatCalendarMonthLabel,
  formatPeriodMonthLabel,
  isSameCalendarMonth,
  nextCalendarMonth,
  previousCalendarMonth,
  type CalendarMonth,
} from "./calendar-month";
import {
  formatBucketPeriodNote,
  formatIncompleteNotice,
  formatNetFlow,
  formatOverviewPeriodNote,
  formatRecordCounts,
  formatSavingsRate,
  hasNoRecords,
  hasUnresolvedRecords,
} from "./financial-overview-presentation";
import { styles } from "./financial-overview.styles";
import { useLocalCalendarMonth } from "./use-local-calendar-month";

// Months of history shown below the selected month (the backend default).
const FINANCIAL_HISTORY_MONTHS = 6;

// The month selection is either "the current month" -- which follows the
// device's local month, so revisiting the screen after a month boundary
// shows the new month -- or one specific earlier month the user navigated
// to. Kept as component state: it is UI selection, not server state.
type MonthSelection = { kind: "current" } | { kind: "month"; month: CalendarMonth };

function FigureRow({
  label,
  value,
  strong = false,
}: {
  label: string;
  value: string;
  strong?: boolean;
}) {
  return (
    <View style={styles.figureRow}>
      <Text style={styles.figureLabel}>{label}</Text>
      <Text style={strong ? styles.figureValueStrong : styles.figureValue}>{value}</Text>
    </View>
  );
}

// The four backend figures of a period, rendered exactly as returned --
// Net and the savings rate are never recomputed here.
function FinancialFigures({
  figures,
  currency,
}: {
  figures: FinancialFlowFigures;
  currency: string;
}) {
  return (
    <View style={styles.figureList}>
      <FigureRow label="Income" value={formatAmount(figures.income_total, currency)} />
      <FigureRow label="Expenses" value={formatAmount(figures.expense_total, currency)} />
      <FigureRow
        label="Net (Income - Expenses)"
        value={formatNetFlow(figures.net_flow, currency)}
        strong
      />
      <FigureRow label="Savings rate" value={formatSavingsRate(figures.savings_rate_percent)} />
    </View>
  );
}

function IncompleteDataWarning({
  figures,
  currency,
}: {
  figures: FinancialFlowFigures;
  currency: string;
}) {
  return (
    <View style={styles.warningBox} accessibilityRole="alert">
      <Text style={styles.warningTitle}>Incomplete data</Text>
      <Text style={styles.warningText}>{formatIncompleteNotice(figures, currency)}</Text>
    </View>
  );
}

function RetryButton({ onRetry, isRetrying }: { onRetry: () => void; isRetrying: boolean }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="Try again"
      accessibilityState={{ disabled: isRetrying }}
      disabled={isRetrying}
      onPress={onRetry}
      style={styles.retryButton}
    >
      {isRetrying ? (
        <ActivityIndicator />
      ) : (
        <Text style={styles.retryButtonText}>Try again</Text>
      )}
    </Pressable>
  );
}

export function FinancialOverviewScreen() {
  const { session } = useAuth();
  const currentMonth = useLocalCalendarMonth();
  const [selection, setSelection] = useState<MonthSelection>({ kind: "current" });

  // A specific month can never be later than the current month; clamping
  // here (instead of in an effect) keeps the selection valid even if the
  // current month has just moved.
  const selectedMonth =
    selection.kind === "current" || compareCalendarMonths(selection.month, currentMonth) > 0
      ? currentMonth
      : selection.month;
  const isAtCurrentMonth = isSameCalendarMonth(selectedMonth, currentMonth);

  // Every key carries the user id, and both queries run only with a
  // session, so one account's figures can never show for another.
  const {
    data: overview,
    isLoading: isOverviewLoading,
    error: overviewError,
    refetch: refetchOverview,
    isFetching: isOverviewFetching,
  } = useQuery({
    queryKey: [
      "analytics",
      "financial-overview",
      session?.user.id,
      selectedMonth.year,
      selectedMonth.month,
    ],
    queryFn: () => getFinancialOverview(selectedMonth.year, selectedMonth.month),
    enabled: Boolean(session),
  });

  const {
    data: trend,
    isLoading: isTrendLoading,
    error: trendError,
    refetch: refetchTrend,
    isFetching: isTrendFetching,
  } = useQuery({
    queryKey: [
      "analytics",
      "income-expense-trend",
      session?.user.id,
      FINANCIAL_HISTORY_MONTHS,
    ],
    queryFn: () => getIncomeExpenseTrend(FINANCIAL_HISTORY_MONTHS),
    enabled: Boolean(session),
  });

  function handlePreviousMonth() {
    setSelection({ kind: "month", month: previousCalendarMonth(selectedMonth) });
  }

  // Never moves past the device's current month; reaching it switches the
  // selection back to "current" so it keeps following the calendar.
  function handleNextMonth() {
    if (isAtCurrentMonth) {
      return;
    }

    const nextMonth = nextCalendarMonth(selectedMonth);

    setSelection(
      isSameCalendarMonth(nextMonth, currentMonth)
        ? { kind: "current" }
        : { kind: "month", month: nextMonth },
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title}>Financial Overview</Text>

        <View style={styles.monthSelector}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Previous month"
            onPress={handlePreviousMonth}
            style={styles.monthButton}
          >
            <Text style={styles.monthButtonText}>‹ Previous</Text>
          </Pressable>

          <Text style={styles.monthLabel} accessibilityRole="header">
            {formatCalendarMonthLabel(selectedMonth)}
          </Text>

          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Next month"
            accessibilityState={{ disabled: isAtCurrentMonth }}
            disabled={isAtCurrentMonth}
            onPress={handleNextMonth}
            style={[styles.monthButton, isAtCurrentMonth && styles.monthButtonDisabled]}
          >
            <Text style={styles.monthButtonText}>Next ›</Text>
          </Pressable>
        </View>

        {/* Section A: the selected month (financial-overview). */}
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Income and expenses</Text>

          {isOverviewLoading ? (
            <ActivityIndicator style={styles.loader} />
          ) : overviewError ? (
            <>
              <Text style={styles.errorText}>
                Unable to load the overview for this month.
              </Text>
              <RetryButton
                onRetry={() => void refetchOverview()}
                isRetrying={isOverviewFetching}
              />
            </>
          ) : overview ? (
            <>
              <Text style={styles.secondaryText}>{formatOverviewPeriodNote(overview)}</Text>

              {overview.data_status === "incomplete_data" ? (
                <IncompleteDataWarning figures={overview} currency={overview.base_currency} />
              ) : null}

              <FinancialFigures figures={overview} currency={overview.base_currency} />

              <Text style={styles.secondaryText}>
                {formatRecordCounts(overview.income_count, overview.expense_count)}
              </Text>

              {overview.period_state !== "future" && hasNoRecords(overview) ? (
                <Text style={styles.noticeText}>
                  No income or expenses recorded for this period.
                </Text>
              ) : null}

              <Text style={styles.noticeText}>
                Net is recorded income minus recorded expenses. It is not an
                account balance or a bank cash flow, and transfers between your
                accounts are not included.
              </Text>
            </>
          ) : null}
        </View>

        {/* Section B: monthly history (income-expense-trend), independent of
            the month selector and of Section A's loading/error state. */}
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Monthly history</Text>

          {isTrendLoading ? (
            <ActivityIndicator style={styles.loader} />
          ) : trendError ? (
            <>
              <Text style={styles.errorText}>Unable to load monthly history.</Text>
              <RetryButton
                onRetry={() => void refetchTrend()}
                isRetrying={isTrendFetching}
              />
            </>
          ) : trend ? (
            // Backend order (oldest first), never re-sorted or filtered.
            trend.buckets.map((bucket) => (
              <View key={bucket.period_start} style={styles.bucketBlock}>
                <Text style={styles.bucketTitle}>
                  {formatPeriodMonthLabel(bucket.period_start)}
                </Text>

                <Text style={styles.secondaryText}>
                  {formatBucketPeriodNote(bucket.is_complete, bucket.effective_end)}
                </Text>

                {hasUnresolvedRecords(bucket) ? (
                  <IncompleteDataWarning figures={bucket} currency={trend.base_currency} />
                ) : null}

                <FinancialFigures figures={bucket} currency={trend.base_currency} />
              </View>
            ))
          ) : null}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
