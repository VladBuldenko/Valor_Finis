import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  SafeAreaView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { getMonthlySummary } from "../../src/features/analytics/analytics.service";
import { signOut } from "../../src/features/auth/auth.service";
import { useAuth } from "../../src/features/auth/auth-context";
import React from "react";

export default function DashboardScreen() {
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
      <View style={styles.content}>
        <Text style={styles.title}>
          Valor Finis
        </Text>

        <Text style={styles.subtitle}>
          Dashboard
        </Text>

        <View style={styles.summary}>
          <Text style={styles.sectionTitle}>
            This month
          </Text>

          {isSummaryLoading ? (
            <ActivityIndicator />
          ) : summaryError ? (
            <Text>
              Unable to load monthly summary.
            </Text>
          ) : (
            <>
              <Text style={styles.amount}>
                €{monthlySummary?.total_spent ?? "0.00"}
              </Text>

              <Text style={styles.expensesCount}>
                {monthlySummary?.expenses_count ?? 0} expenses
              </Text>
            </>
          )}
        </View>

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
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  content: {
    flex: 1,
    paddingHorizontal: 24,
    paddingTop: 32,
  },
  title: {
    fontSize: 32,
    fontWeight: "700",
  },
  subtitle: {
    fontSize: 20,
    marginTop: 8,
  },
  summary: {
    marginTop: 32,
    padding: 20,
    borderWidth: 1,
    borderRadius: 12,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: "600",
  },
  amount: {
    fontSize: 32,
    fontWeight: "700",
    marginTop: 12,
  },
  expensesCount: {
    fontSize: 16,
    marginTop: 8,
  },
  button: {
    alignItems: "center",
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 14,
    marginTop: 32,
  },
  buttonText: {
    fontSize: 16,
    fontWeight: "600",
  },
});