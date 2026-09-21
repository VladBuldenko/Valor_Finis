import { useState } from "react";
import { useLocalSearchParams, useRouter } from "expo-router";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  SafeAreaView,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";

import { useAuth } from "../auth/auth-context";
import {
  normalizeGoalDecimalAmount,
  validateGoalDecimalAmount,
} from "./goal-amount-validation";
import { getGoalErrorMessage } from "./goal-error-message";
import { validateGoalTransactionForm } from "./goal-transaction-validation";
import {
  createGoalTransaction,
  getGoalTransactions,
  getGoals,
} from "./goal.service";
import { styles } from "./goals.styles";
import type {
  GoalStatus,
  GoalTransaction,
  GoalTransactionCreateInput,
  GoalTransactionType,
} from "./goal.types";

const STATUS_LABELS: Record<GoalStatus, string> = {
  active: "Active",
  completed: "Completed",
  archived: "Archived",
};

// Readable labels for every transaction type a client may see in history --
// including opening_balance, a migration/system-created entry a client can
// never create through this screen (see the contribution/withdrawal-only
// toggle below), but which must still be rendered as normal history.
const TRANSACTION_TYPE_LABELS: Record<GoalTransactionType, string> = {
  opening_balance: "Opening balance",
  contribution: "Contribution",
  withdrawal: "Withdrawal",
};

// Only these two types are ever submittable from this screen --
// opening_balance is system/migration-only (the backend rejects a client
// request for it with 422), so it is never offered as a toggle option.
const SUBMITTABLE_TRANSACTION_TYPES: ("contribution" | "withdrawal")[] = [
  "contribution",
  "withdrawal",
];

// Formats a transaction's amount for display with a +/- presentation
// prefix (opening_balance/contribution add to the balance, withdrawal
// subtracts). This is string concatenation only -- the amount itself is
// never parsed into a JavaScript Number, matching every other financial
// display in this app.
function formatTransactionAmount(transaction: GoalTransaction): string {
  const prefix = transaction.type === "withdrawal" ? "-" : "+";

  return `${prefix}${transaction.amount}`;
}

export function GoalDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { session, isLoading: isAuthLoading } = useAuth();
  const queryClient = useQueryClient();
  const router = useRouter();

  // There is no GET /goals/{id} endpoint -- the goal is resolved from the
  // already-fetched ["goals", userId] list, the same query key and data
  // every other Goal screen uses (see goal-edit-screen.tsx). Balance
  // (current_amount) on this resolved Goal is already ledger-derived by
  // the backend (VF-016D); this screen never recalculates it locally.
  const {
    data: goal,
    isLoading: isGoalLoading,
    error: goalError,
  } = useQuery({
    queryKey: ["goals", session?.user.id],
    queryFn: getGoals,
    enabled: Boolean(session),
    select: (goals) => goals.find((candidate) => candidate.id === id),
  });

  const {
    data: transactions = [],
    isLoading: isTransactionsLoading,
    error: transactionsError,
  } = useQuery({
    queryKey: ["goals", "transactions", session?.user.id, id],
    queryFn: () => getGoalTransactions(id),
    enabled: Boolean(session) && Boolean(id),
  });

  const [transactionType, setTransactionType] = useState<
    "contribution" | "withdrawal"
  >("contribution");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");

  const createTransactionMutation = useMutation({
    mutationFn: (payload: GoalTransactionCreateInput) =>
      createGoalTransaction(id, payload),

    onSuccess: async () => {
      setAmount("");
      setDescription("");

      // A contribution/withdrawal changes the Goal's ledger-derived
      // balance, Goal Progress analytics, and this goal's own transaction
      // history -- all three must be invalidated together. The new
      // balance/progress always come from a refetch, never from a value
      // computed locally here.
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["goals", session?.user.id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["analytics", "goal-progress", session?.user.id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["goals", "transactions", session?.user.id, id],
        }),
      ]);
    },

    // `variables` is the exact payload passed to .mutate() for this
    // specific failed call, read here instead of the outer transactionType
    // state so the alert title always matches the request that actually
    // failed, even if the user has since toggled the control.
    onError: (mutationError, variables) => {
      const title =
        variables.type === "withdrawal"
          ? "Withdrawal failed"
          : "Contribution failed";

      Alert.alert(
        title,
        getGoalErrorMessage(mutationError, "Unable to create transaction."),
      );
    },
  });

  function handleSubmitTransaction() {
    // Guards against duplicate submissions from a double tap while the
    // request is already in flight.
    if (createTransactionMutation.isPending) {
      return;
    }

    const validationError = validateGoalTransactionForm({
      amount,
      description,
    });

    if (validationError) {
      Alert.alert("Invalid transaction", validationError);
      return;
    }

    const trimmedDescription = description.trim();

    createTransactionMutation.mutate({
      type: transactionType,
      amount: normalizeGoalDecimalAmount(amount),
      ...(trimmedDescription ? { description: trimmedDescription } : {}),
    });
  }

  if (isAuthLoading || isGoalLoading) {
    return (
      <SafeAreaView style={styles.container}>
        <ActivityIndicator style={styles.loader} />
      </SafeAreaView>
    );
  }

  if (goalError) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.content}>
          <Text style={styles.errorText}>Unable to load goal.</Text>
        </View>
      </SafeAreaView>
    );
  }

  if (!goal) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.content}>
          <Text style={styles.secondaryText}>Goal not found.</Text>

          <Pressable style={styles.button} onPress={() => router.back()}>
            <Text style={styles.buttonText}>Back to goals</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  const amountValidationError = amount
    ? validateGoalDecimalAmount(amount, "Amount")
    : null;
  const canSubmitTransaction =
    Boolean(amount) && !amountValidationError && !createTransactionMutation.isPending;

  return (
    <SafeAreaView style={styles.container}>
      <KeyboardAvoidingView
        style={styles.container}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <ScrollView
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
        >
          <Text style={styles.title}>{goal.name}</Text>

          <Text style={styles.secondaryText}>{STATUS_LABELS[goal.status]}</Text>

          <Text style={styles.amount}>
            {goal.current_amount} {goal.currency}
          </Text>

          <Text style={styles.secondaryText}>
            Target: {goal.target_amount} {goal.currency}
          </Text>

          <Text style={styles.secondaryText}>
            {goal.target_date
              ? `Target date: ${goal.target_date}`
              : "No target date"}
          </Text>

          <Text style={styles.sectionTitle}>Add funds</Text>

          <View style={styles.typeToggleRow}>
            {SUBMITTABLE_TRANSACTION_TYPES.map((option) => (
              <Pressable
                key={option}
                style={[
                  styles.typeToggleButton,
                  transactionType === option && styles.typeToggleButtonSelected,
                ]}
                onPress={() => setTransactionType(option)}
              >
                <Text
                  style={[
                    styles.typeToggleButtonText,
                    transactionType === option &&
                      styles.typeToggleButtonTextSelected,
                  ]}
                >
                  {TRANSACTION_TYPE_LABELS[option]}
                </Text>
              </Pressable>
            ))}
          </View>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Amount *</Text>

            <TextInput
              style={styles.input}
              placeholder="0.00"
              value={amount}
              onChangeText={setAmount}
              keyboardType="decimal-pad"
            />
          </View>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Description</Text>

            <TextInput
              style={[styles.input, styles.inputOptional]}
              placeholder="Optional note"
              value={description}
              onChangeText={setDescription}
            />
          </View>

          <Pressable
            disabled={!canSubmitTransaction}
            onPress={handleSubmitTransaction}
            style={[styles.button, styles.formGroup]}
          >
            {createTransactionMutation.isPending ? (
              <ActivityIndicator />
            ) : (
              <Text style={styles.buttonText}>
                {transactionType === "withdrawal"
                  ? "Withdraw"
                  : "Add contribution"}
              </Text>
            )}
          </Pressable>

          <Text style={styles.sectionTitle}>Transaction history</Text>

          {isTransactionsLoading ? (
            <ActivityIndicator style={styles.loader} />
          ) : transactionsError ? (
            <Text style={styles.errorText}>
              Unable to load transaction history.
            </Text>
          ) : transactions.length === 0 ? (
            <Text style={styles.secondaryText}>No transactions yet.</Text>
          ) : (
            <View style={styles.historyList}>
              {transactions.map((transaction) => (
                <View key={transaction.id} style={styles.historyRow}>
                  <View style={styles.historyRowHeader}>
                    <Text style={styles.historyType}>
                      {TRANSACTION_TYPE_LABELS[transaction.type]}
                    </Text>

                    <Text style={styles.historyAmount}>
                      {formatTransactionAmount(transaction)} {goal.currency}
                    </Text>
                  </View>

                  {transaction.description ? (
                    <Text style={styles.historyDescription}>
                      {transaction.description}
                    </Text>
                  ) : null}

                  <Text style={styles.historyDate}>
                    {transaction.created_at}
                  </Text>
                </View>
              ))}
            </View>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
