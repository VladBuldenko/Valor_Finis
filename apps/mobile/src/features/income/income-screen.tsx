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
import { getAccounts } from "../accounts/account.service";
import type { Account } from "../accounts/account.types";
import { getIncome } from "./income.service";
import { styles } from "./income.styles";
import { INCOME_SOURCE_LABELS, type Income } from "./income.types";

// Presentation-only label for an Income's linked Account. Uses the shared
// ["accounts", userId] list (active and archived) purely to show a name --
// never to compute or display a balance. A raw account_id is never shown:
// while Accounts are still loading the label stays neutral, and an id the
// list cannot resolve gets "Linked account unavailable".
function getLinkedAccountLabel(
  income: Income,
  accounts: Account[],
  isAccountsLoading: boolean,
): string | null {
  if (income.account_id === null) {
    return null;
  }

  if (isAccountsLoading) {
    return "Linked account";
  }

  const account = accounts.find(
    (candidate) => candidate.id === income.account_id,
  );

  if (!account) {
    return "Linked account unavailable";
  }

  return account.status === "archived"
    ? `Account: ${account.name} (archived)`
    : `Account: ${account.name}`;
}

export function IncomeScreen() {
  const { session } = useAuth();

  const {
    data: incomeRecords = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["income", session?.user.id],
    queryFn: getIncome,
    enabled: Boolean(session),
  });

  // Same query key/data as the Accounts screen, so an Account rename or
  // archive is reflected here without a separate fetch path.
  const { data: accounts = [], isLoading: isAccountsLoading } = useQuery({
    queryKey: ["accounts", session?.user.id],
    queryFn: getAccounts,
    enabled: Boolean(session),
  });

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title}>Income</Text>

        <Link href="/income/new" asChild>
          <Pressable style={styles.button}>
            <Text style={styles.buttonText}>Add income</Text>
          </Pressable>
        </Link>

        {isLoading ? (
          <ActivityIndicator style={styles.loader} />
        ) : error ? (
          <Text style={styles.errorText}>Unable to load income.</Text>
        ) : incomeRecords.length === 0 ? (
          <Text style={styles.secondaryText}>No income yet.</Text>
        ) : (
          <View style={styles.list}>
            {incomeRecords.map((income) => {
              const linkedAccountLabel = getLinkedAccountLabel(
                income,
                accounts,
                isAccountsLoading,
              );

              return (
                <View key={income.id} style={styles.card}>
                  <Text style={styles.name}>
                    {INCOME_SOURCE_LABELS[income.source]}
                  </Text>

                  <Text style={styles.amount}>
                    {income.amount} {income.currency}
                  </Text>

                  <Text style={styles.secondaryText}>{income.received_at}</Text>

                  {income.description ? (
                    <Text style={styles.secondaryText}>
                      {income.description}
                    </Text>
                  ) : null}

                  {linkedAccountLabel ? (
                    <Text style={styles.secondaryText}>
                      {linkedAccountLabel}
                    </Text>
                  ) : null}

                  <Link
                    href={{
                      pathname: "/income/[id]/edit",
                      params: { id: income.id },
                    }}
                    asChild
                  >
                    <Pressable style={styles.editButton}>
                      <Text style={styles.editButtonText}>Edit income</Text>
                    </Pressable>
                  </Link>
                </View>
              );
            })}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
