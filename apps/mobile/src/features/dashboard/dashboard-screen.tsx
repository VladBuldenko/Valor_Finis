import { useState } from "react";
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
    getMonthlySummary,
  } from "../analytics/analytics.service";

import { Link } from "expo-router";
import { useAuth } from "../auth/auth-context";
import { signOut } from "../auth/auth.service";
import { styles } from "./dashboard.styles";
import React from "react";

export function DashboardScreen() {
  const { session } = useAuth();
  const [isSigningOut, setIsSigningOut] = useState(false);

  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth() + 1;

  const {
    data: monthlySummary,
    isLoading: isSummaryLoading,
    error: summaryError,
  } = useQuery({
    queryKey: [
      "analytics",
      "monthly-summary",
      session?.user.id,
      year,
      month,
    ],
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
    queryKey: [
      "analytics",
      "budget-status",
      session?.user.id,
    ],
    queryFn: getBudgetStatus,
    enabled: Boolean(session),
  });

  async function handleSignOut() {
    try {
      setIsSigningOut(true);

      await signOut();
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Unable to sign out.";

      Alert.alert("Sign out failed", message);
    } finally {
      setIsSigningOut(false);
    }
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title}>
          Valor Finis
        </Text>

        <Text style={styles.subtitle}>
          Dashboard
        </Text>

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>
            This month
          </Text>

          {isSummaryLoading ? (
            <ActivityIndicator style={styles.loader} />
          ) : summaryError ? (
            <Text style={styles.errorText}>
              Unable to load monthly summary.
            </Text>
          ) : (
            <>
              <Text style={styles.amount}>
                €{monthlySummary?.total_spent ?? "0.00"}
              </Text>

              <Text style={styles.secondaryText}>
                {monthlySummary?.expenses_count ?? 0} expenses
              </Text>
            </>
          )}
        </View>

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>
            Spending by category
          </Text>

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
                      {category.expenses_count} expenses
                    </Text>
                  </View>

                  <Text style={styles.categoryAmount}>
                    €{category.total_spent}
                  </Text>
                </View>
              ))}
            </View>
          )}
        </View>
        <View style={styles.card}>
            <Text style={styles.sectionTitle}>
                Budget status
            </Text>

            {isBudgetStatusLoading ? (
                <ActivityIndicator style={styles.loader} />
            ) : budgetStatusError ? (
                <Text style={styles.errorText}>
                Unable to load budget status.
                </Text>
            ) : budgetStatus.length === 0 ? (
                <Text style={styles.secondaryText}>
                No budgets yet.
                </Text>
            ) : (
                <View style={styles.categoryList}>
                {budgetStatus.map((budget) => (
                    <View
                    key={budget.budget_id}
                    style={styles.categoryRow}
                    >
                    <View style={styles.categoryDetails}>
                        <Text style={styles.categoryName}>
                        {budget.budget_name}
                        </Text>

                        <Text style={styles.secondaryText}>
                        Spent: €{budget.spent} / €{budget.limit_amount}
                        </Text>

                        <Text style={styles.secondaryText}>
                        {budget.is_exceeded
                            ? `Exceeded by €${budget.exceeded_amount}`
                            : `Remaining €${budget.remaining}`}
                        </Text>
                    </View>
                    </View>
                ))}
                </View>
            )}
        </View>
        <Link href="/expenses" asChild>
            <Pressable style={styles.button}>
                <Text style={styles.buttonText}>
                Expenses
                </Text>
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
            <Text style={styles.buttonText}>
              Log out
            </Text>
          )}
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}