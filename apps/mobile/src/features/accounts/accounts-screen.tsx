import { useState } from "react";
import { Link } from "expo-router";
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
import { getAccounts } from "./account.service";
import { styles } from "./accounts.styles";
import type { Account, AccountStatus, AccountType } from "./account.types";

// Readable labels for the backend's lowercase literals. Both are rendered
// as-is from the backend -- presentation-only text formatting, never a
// client-side computation (the backend remains the sole authority on an
// account's type/status).
const TYPE_LABELS: Record<AccountType, string> = {
  checking: "Checking",
  savings: "Savings",
  cash: "Cash",
};

const STATUS_LABELS: Record<AccountStatus, string> = {
  active: "Active",
  archived: "Archived",
};

// Local presentation-only view mode, mirroring ../goals/goals-screen.tsx's
// GoalListView -- component state, not a backend/domain concept. Unlike
// Goal (three statuses, "current" covers two of them), Account only has
// two statuses, so the partition here is a direct, exhaustive split on
// Account.status.
type AccountListView = "active" | "archived";

function matchesAccountListView(
  account: Account,
  view: AccountListView,
): boolean {
  return account.status === view;
}

// The empty-state message must reflect the currently filtered view, not
// the full unfiltered accounts list -- e.g. a user with only archived
// accounts must never see "No accounts yet." while viewing Active.
function getAccountsEmptyMessage(
  view: AccountListView,
  totalAccountsCount: number,
): string {
  if (totalAccountsCount === 0) {
    return "No accounts yet.";
  }

  return view === "archived" ? "No archived accounts." : "No active accounts.";
}

export function AccountsScreen() {
  const { session } = useAuth();

  const [listView, setListView] = useState<AccountListView>("active");

  const {
    data: accounts = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["accounts", session?.user.id],
    queryFn: getAccounts,
    enabled: Boolean(session),
  });

  const visibleAccounts = accounts.filter((account) =>
    matchesAccountListView(account, listView),
  );

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title}>Accounts</Text>

        <Link href="/accounts/new" asChild>
          <Pressable style={styles.button}>
            <Text style={styles.buttonText}>Add account</Text>
          </Pressable>
        </Link>

        <View style={styles.typeToggleRow}>
          <Pressable
            accessibilityRole="button"
            accessibilityState={{ selected: listView === "active" }}
            style={[
              styles.typeToggleButton,
              listView === "active" && styles.typeToggleButtonSelected,
            ]}
            onPress={() => setListView("active")}
          >
            <Text
              style={[
                styles.typeToggleButtonText,
                listView === "active" && styles.typeToggleButtonTextSelected,
              ]}
            >
              Active
            </Text>
          </Pressable>

          <Pressable
            accessibilityRole="button"
            accessibilityState={{ selected: listView === "archived" }}
            style={[
              styles.typeToggleButton,
              listView === "archived" && styles.typeToggleButtonSelected,
            ]}
            onPress={() => setListView("archived")}
          >
            <Text
              style={[
                styles.typeToggleButtonText,
                listView === "archived" &&
                  styles.typeToggleButtonTextSelected,
              ]}
            >
              Archived
            </Text>
          </Pressable>
        </View>

        {isLoading ? (
          <ActivityIndicator style={styles.loader} />
        ) : error ? (
          <Text style={styles.errorText}>Unable to load accounts.</Text>
        ) : visibleAccounts.length === 0 ? (
          <Text style={styles.secondaryText}>
            {getAccountsEmptyMessage(listView, accounts.length)}
          </Text>
        ) : (
          <View style={styles.list}>
            {visibleAccounts.map((account) => (
              <View key={account.id} style={styles.card}>
                <Text style={styles.name}>{account.name}</Text>

                <Text style={styles.secondaryText}>
                  {TYPE_LABELS[account.type]}
                </Text>

                <Text style={styles.secondaryText}>
                  {STATUS_LABELS[account.status]}
                </Text>

                <Text style={styles.amount}>
                  {account.current_balance} {account.currency}
                </Text>

                <Link
                  href={{
                    pathname: "/accounts/[id]",
                    params: { id: account.id },
                  }}
                  asChild
                >
                  <Pressable style={styles.editButton}>
                    <Text style={styles.editButtonText}>Open account</Text>
                  </Pressable>
                </Link>

                <Link
                  href={{
                    pathname: "/accounts/[id]/edit",
                    params: { id: account.id },
                  }}
                  asChild
                >
                  <Pressable style={styles.editButton}>
                    <Text style={styles.editButtonText}>Edit account</Text>
                  </Pressable>
                </Link>
              </View>
            ))}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
