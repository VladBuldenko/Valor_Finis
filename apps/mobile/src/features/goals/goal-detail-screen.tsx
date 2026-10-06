import { useRef, useState } from "react";
import * as Crypto from "expo-crypto";
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
import {
  canonicalizeGoalAmount,
  getGoalTransactionDisplayDate,
  resolveGoalTransactionAttempt,
  toGoalTransactionCreateInput,
  type GoalTransactionAttempt,
} from "./goal-transaction-attempts";
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

// An archived goal accepts withdrawals but no new contributions (VF-020A
// P10, enforced by the backend with 409) -- so only withdrawal is offered
// for it. Active and completed goals offer both. The backend stays the
// authority; this only avoids offering an action that would be rejected.
function getSubmittableTransactionTypes(
  status: GoalStatus,
): ("contribution" | "withdrawal")[] {
  return status === "archived" ? ["withdrawal"] : SUBMITTABLE_TRANSACTION_TYPES;
}

// Returns the type the form will actually submit: the user's selection when
// it is still offered for the goal's status, else the first offered type
// (e.g. a goal archived while "Contribution" was selected).
function resolveSelectedTransactionType(
  status: GoalStatus,
  selectedType: "contribution" | "withdrawal",
): "contribution" | "withdrawal" {
  const availableTypes = getSubmittableTransactionTypes(status);

  return availableTypes.includes(selectedType) ? selectedType : availableTypes[0];
}

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

  // Create idempotency attempts of this form instance (see
  // resolveGoalTransactionAttempt): kept across failed submissions so a
  // retry of the same payload reuses its client_request_id, cleared after
  // a success, and discarded when the screen closes. A ref, not state --
  // it never affects rendering and is only read in event handlers.
  const createAttemptsRef = useRef<GoalTransactionAttempt[]>([]);

  const createTransactionMutation = useMutation({
    mutationFn: (payload: GoalTransactionCreateInput) =>
      createGoalTransaction(id, payload),

    // 201 (new) and 200 (exact replay of an earlier, possibly lost,
    // attempt) are the same success: the body is the one stored
    // transaction either way, and the refetch below shows it exactly once.
    onSuccess: async () => {
      createAttemptsRef.current = [];
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
    // failed, even if the user has since toggled the control. The attempts
    // are deliberately kept: the request may have been committed even
    // though it failed here, so resubmitting the unchanged form must reuse
    // the same key.
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
    if (createTransactionMutation.isPending || !goal) {
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

    const { attempt, attempts } = resolveGoalTransactionAttempt(
      createAttemptsRef.current,
      {
        goalId: goal.id,
        type: resolveSelectedTransactionType(goal.status, transactionType),
        amount: canonicalizeGoalAmount(normalizeGoalDecimalAmount(amount)),
        description: trimmedDescription ? trimmedDescription : null,
      },
      () => Crypto.randomUUID(),
    );

    createAttemptsRef.current = attempts;
    createTransactionMutation.mutate(toGoalTransactionCreateInput(attempt));
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
  const availableTransactionTypes = getSubmittableTransactionTypes(goal.status);
  const selectedTransactionType = resolveSelectedTransactionType(
    goal.status,
    transactionType,
  );

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

          {goal.status === "archived" ? (
            <>
              <Text style={styles.sectionTitle}>Withdraw funds</Text>

              <Text style={styles.secondaryText}>
                Archived goals cannot receive contributions. Withdrawals are
                still available.
              </Text>
            </>
          ) : (
            <>
              <Text style={styles.sectionTitle}>Add funds</Text>

              <View style={styles.typeToggleRow}>
                {availableTransactionTypes.map((option) => (
                  <Pressable
                    key={option}
                    style={[
                      styles.typeToggleButton,
                      selectedTransactionType === option &&
                        styles.typeToggleButtonSelected,
                    ]}
                    onPress={() => setTransactionType(option)}
                  >
                    <Text
                      style={[
                        styles.typeToggleButtonText,
                        selectedTransactionType === option &&
                          styles.typeToggleButtonTextSelected,
                      ]}
                    >
                      {TRANSACTION_TYPE_LABELS[option]}
                    </Text>
                  </Pressable>
                ))}
              </View>
            </>
          )}

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
                {selectedTransactionType === "withdrawal"
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
                    {getGoalTransactionDisplayDate(transaction)}
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
