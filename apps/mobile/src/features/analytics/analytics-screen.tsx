import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ActivityIndicator,
  Pressable,
  SafeAreaView,
  ScrollView,
  Text,
  View,
} from "react-native";

import { useAuth } from "../auth/auth-context";
import {
  formatAmount,
  formatDateRange,
  formatDirectionLabel,
  formatExpenseCount,
  formatForecastStatusLabel,
  formatPercent,
  formatPeriodLabel,
  formatUnresolvedNotice,
} from "./analytics-presentation";
import {
  getCategoryTrend,
  getSpendingForecast,
  getSpendingTrend,
} from "./analytics.service";
import { styles } from "./analytics.styles";
import type {
  PeriodOverPeriodComparison,
  SpendingTrendBucket,
  SpendingTrendPeriod,
} from "./analytics.types";

const TREND_PERIODS: SpendingTrendPeriod[] = ["day", "week", "month"];

// Category Trend stays fixed to a monthly, 6-bucket view for VF-015E --
// the screen does not yet expose its own period/count controls for this
// section (Spending Trend's own switcher is unrelated and does not drive
// this section).
const CATEGORY_TREND_PERIOD: SpendingTrendPeriod = "month";
const CATEGORY_TREND_COUNT = 6;

// Shared bucket row, reused by both the Spending Trend and Category Trend
// sections -- identical presentation rules apply to both (every bucket
// the backend returns is shown, including zero/incomplete ones).
function BucketRow({
  bucket,
  currency,
}: {
  bucket: SpendingTrendBucket;
  currency: string;
}) {
  return (
    <View style={styles.bucketRow}>
      <View style={styles.bucketDetails}>
        <Text style={styles.bucketRange}>
          {formatDateRange(bucket.period_start, bucket.period_end)}
          {!bucket.is_complete ? " · In progress" : ""}
        </Text>

        <Text style={styles.secondaryText}>
          {formatExpenseCount(bucket.expenses_count)}
        </Text>

        {bucket.unresolved_expenses_count > 0 ? (
          <Text style={styles.noticeText}>
            {formatUnresolvedNotice(bucket.unresolved_expenses_count)}
          </Text>
        ) : null}
      </View>

      <Text style={styles.bucketAmount}>
        {formatAmount(bucket.total_spent, currency)}
      </Text>
    </View>
  );
}

// Shared period-over-period comparison block, reused by both the overall
// Spending Trend and each Category Trend item.
function PeriodOverPeriodSummary({
  comparison,
  currency,
}: {
  comparison: PeriodOverPeriodComparison;
  currency: string;
}) {
  return (
    <View style={styles.comparisonBox}>
      <Text style={styles.secondaryText}>
        {formatAmount(comparison.previous_total_spent, currency)}
        {" → "}
        {formatAmount(comparison.current_total_spent, currency)}
      </Text>

      <Text style={styles.secondaryText}>
        Change: {formatAmount(comparison.absolute_change, currency)} (
        {formatDirectionLabel(comparison.direction)})
      </Text>

      <Text style={styles.secondaryText}>
        {comparison.percent_change !== null
          ? formatPercent(comparison.percent_change)
          : "Percentage change unavailable because the previous period was zero."}
      </Text>
    </View>
  );
}

export function AnalyticsScreen() {
  const { session } = useAuth();
  const [selectedPeriod, setSelectedPeriod] =
    useState<SpendingTrendPeriod>("month");

  const {
    data: forecast,
    isLoading: isForecastLoading,
    error: forecastError,
  } = useQuery({
    queryKey: ["analytics", "spending-forecast", session?.user.id],
    queryFn: getSpendingForecast,
    enabled: Boolean(session),
  });

  const {
    data: trend,
    isLoading: isTrendLoading,
    error: trendError,
  } = useQuery({
    queryKey: [
      "analytics",
      "spending-trend",
      session?.user.id,
      selectedPeriod,
    ],
    queryFn: () => getSpendingTrend(selectedPeriod),
    enabled: Boolean(session),
  });

  const {
    data: categoryTrend,
    isLoading: isCategoryTrendLoading,
    error: categoryTrendError,
  } = useQuery({
    queryKey: [
      "analytics",
      "category-trend",
      session?.user.id,
      CATEGORY_TREND_PERIOD,
      CATEGORY_TREND_COUNT,
    ],
    queryFn: () =>
      getCategoryTrend(CATEGORY_TREND_PERIOD, CATEGORY_TREND_COUNT),
    enabled: Boolean(session),
  });

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title}>Analytics</Text>

        {/* Section A: current-month spending forecast (VF-015D). */}
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Spending forecast</Text>

          {isForecastLoading ? (
            <ActivityIndicator style={styles.loader} />
          ) : forecastError ? (
            <Text style={styles.errorText}>
              Unable to load spending forecast.
            </Text>
          ) : forecast ? (
            <>
              <Text style={styles.secondaryText}>
                {formatForecastStatusLabel(forecast.forecast_status)}
              </Text>

              <Text style={styles.amount}>
                {formatAmount(forecast.spent_to_date, forecast.base_currency)}
              </Text>

              <Text style={styles.secondaryText}>
                Spent so far · {forecast.days_elapsed} of{" "}
                {forecast.days_in_month} days
              </Text>

              {/* forecast_status is the authoritative state machine here -
                  never inferred from whether average_daily_spending/
                  projected_spending happen to be null. The backend
                  contract guarantees both are non-null exactly when
                  forecast_status is "available" (see
                  SpendingForecastResponse in analytics.types.ts), so the
                  non-null assertions below only satisfy TypeScript; they
                  are not the availability decision itself. */}
              {forecast.forecast_status === "available" ? (
                <>
                  <Text style={styles.secondaryText}>
                    Average per day:{" "}
                    {formatAmount(
                      forecast.average_daily_spending!,
                      forecast.base_currency,
                    )}
                  </Text>

                  <Text style={styles.secondaryText}>
                    Projected month total:{" "}
                    {formatAmount(
                      forecast.projected_spending!,
                      forecast.base_currency,
                    )}
                  </Text>
                </>
              ) : (
                <>
                  <Text style={styles.noticeText}>
                    Forecast unavailable because some expenses are not
                    included in the base-currency total.
                  </Text>

                  <Text style={styles.secondaryText}>
                    {forecast.unresolved_expenses_count} unresolved
                  </Text>
                </>
              )}
            </>
          ) : null}
        </View>

        {/* Section B: historical spending trend (VF-015B). */}
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Spending trend</Text>

          <View style={styles.periodSwitcher}>
            {TREND_PERIODS.map((period) => {
              const isSelected = period === selectedPeriod;

              return (
                <Pressable
                  key={period}
                  onPress={() => setSelectedPeriod(period)}
                  style={[
                    styles.periodButton,
                    isSelected && styles.periodButtonSelected,
                  ]}
                >
                  <Text
                    style={[
                      styles.periodButtonText,
                      isSelected && styles.periodButtonTextSelected,
                    ]}
                  >
                    {formatPeriodLabel(period)}
                  </Text>
                </Pressable>
              );
            })}
          </View>

          {isTrendLoading ? (
            <ActivityIndicator style={styles.loader} />
          ) : trendError ? (
            <Text style={styles.errorText}>
              Unable to load spending trend.
            </Text>
          ) : trend ? (
            <>
              <View style={styles.bucketList}>
                {trend.buckets.map((bucket) => (
                  <BucketRow
                    key={bucket.period_start}
                    bucket={bucket}
                    currency={trend.base_currency}
                  />
                ))}
              </View>

              {trend.period_over_period ? (
                <PeriodOverPeriodSummary
                  comparison={trend.period_over_period}
                  currency={trend.base_currency}
                />
              ) : null}
            </>
          ) : null}
        </View>

        {/* Section C: category spending trends (VF-015C). */}
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Category trends</Text>

          {isCategoryTrendLoading ? (
            <ActivityIndicator style={styles.loader} />
          ) : categoryTrendError ? (
            <Text style={styles.errorText}>
              Unable to load category trends.
            </Text>
          ) : categoryTrend ? (
            categoryTrend.categories.length === 0 ? (
              <Text style={styles.secondaryText}>
                No category spending in this period yet.
              </Text>
            ) : (
              categoryTrend.categories.map((category) => (
                <View
                  key={category.category_id ?? "uncategorized"}
                  style={styles.categoryBlock}
                >
                  <Text style={styles.categoryName}>
                    {category.category_name}
                  </Text>

                  {category.buckets.map((bucket) => (
                    <BucketRow
                      key={bucket.period_start}
                      bucket={bucket}
                      currency={categoryTrend.base_currency}
                    />
                  ))}

                  {category.period_over_period ? (
                    <PeriodOverPeriodSummary
                      comparison={category.period_over_period}
                      currency={categoryTrend.base_currency}
                    />
                  ) : null}
                </View>
              ))
            )
          ) : null}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
