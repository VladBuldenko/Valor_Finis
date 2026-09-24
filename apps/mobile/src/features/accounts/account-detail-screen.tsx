import { useState } from "react";
import { Link, useLocalSearchParams, useRouter } from "expo-router";
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
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useAuth } from "../auth/auth-context";
import {
  normalizeAccountDecimalAmount,
  validateAccountDecimalAmount,
} from "./account-amount-validation";
import { getAccountErrorMessage } from "./account-error-message";
import { validateAccountTransactionForm } from "./account-transaction-validation";
import {
  createAccountTransaction,
  deleteAccount,
  getAccountTransactions,
  getAccounts,
  updateAccount,
} from "./account.service";
import { styles } from "./accounts.styles";
import type {
  AccountStatus,
  AccountTransaction,
  AccountTransactionCreateInput,
  AccountTransactionKind,
  AccountType,
} from "./account.types";

const TYPE_LABELS: Record<AccountType, string> = {
  checking: "Checking",
  savings: "Savings",
  cash: "Cash",
};

const STATUS_LABELS: Record<AccountStatus, string> = {
  active: "Active",
  archived: "Archived",
};

// Readable labels for every transaction kind a client may see in history --
// including opening_balance/income/expense, which a client can never
// create through this screen (see the credit/debit-only toggle below), but
// which must still be rendered as normal history. Mirrors
// ../goals/goal-detail-screen.tsx's TRANSACTION_TYPE_LABELS.
const KIND_LABELS: Record<AccountTransactionKind, string> = {
  opening_balance: "Opening balance",
  adjustment: "Adjustment",
  income: "Income",
  expense: "Expense",
};

// Only credit/debit are ever submittable from this screen's Add adjustment
// form -- the backend always creates kind="adjustment" for every row this
// endpoint produces, and there is no client-submitted kind at all.
const SUBMITTABLE_DIRECTIONS: ("credit" | "debit")[] = ["credit", "debit"];

// Formats a transaction's amount for display with a +/- presentation
// prefix. Sign comes from `direction`, NEVER inferred from `kind` --
// unlike GoalTransaction (which has no separate direction column and
// infers sign from `type`), every AccountTransaction row states its own
// sign explicitly. This is string concatenation only -- the amount itself
// is never parsed into a JavaScript Number, matching every other
// financial display in this app.
function formatTransactionAmount(transaction: AccountTransaction): string {
  const prefix = transaction.direction === "debit" ? "-" : "+";

  return `${prefix}${transaction.amount}`;
}

export function AccountDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { session, isLoading: isAuthLoading } = useAuth();
  const queryClient = useQueryClient();
  const router = useRouter();

  // There is no GET /accounts/{id} endpoint -- the account is resolved
  // from the already-fetched ["accounts", userId] list, the same query key
  // and data every other Account screen uses. current_balance on this
  // resolved Account is already ledger-derived by the backend; this screen
  // never recalculates it locally.
  const {
    data: account,
    isLoading: isAccountLoading,
    error: accountError,
  } = useQuery({
    queryKey: ["accounts", session?.user.id],
    queryFn: getAccounts,
    enabled: Boolean(session),
    select: (accounts) => accounts.find((candidate) => candidate.id === id),
  });

  const {
    data: transactions = [],
    isLoading: isTransactionsLoading,
    error: transactionsError,
  } = useQuery({
    queryKey: ["accounts", "transactions", session?.user.id, id],
    queryFn: () => getAccountTransactions(id),
    enabled: Boolean(session) && Boolean(id),
  });

  const [direction, setDirection] = useState<"credit" | "debit">("credit");
  const [amount, setAmount] = useState("");
  const [transactionDate, setTransactionDate] = useState("");
  const [description, setDescription] = useState("");

  const createTransactionMutation = useMutation({
    mutationFn: (payload: AccountTransactionCreateInput) =>
      createAccountTransaction(id, payload),

    onSuccess: async () => {
      setAmount("");
      setTransactionDate("");
      setDescription("");

      // An adjustment changes the Account's ledger-derived current_balance
      // (the list/detail query) and this account's own transaction
      // history -- both must be invalidated together. The new balance
      // always comes from a refetch, never from a value computed locally
      // here.
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["accounts", session?.user.id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["accounts", "transactions", session?.user.id, id],
        }),
      ]);
    },

    onError: (mutationError, variables) => {
      const title = variables.direction === "debit" ? "Debit failed" : "Credit failed";

      Alert.alert(
        title,
        getAccountErrorMessage(mutationError, "Unable to create transaction."),
      );
    },
  });

  const archiveMutation = useMutation({
    mutationFn: (nextStatus: AccountStatus) =>
      updateAccount(id, { status: nextStatus }),

    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["accounts", session?.user.id],
      });
    },

    onError: (mutationError, nextStatus) => {
      const title =
        nextStatus === "archived" ? "Archive failed" : "Reactivate failed";

      Alert.alert(
        title,
        getAccountErrorMessage(mutationError, "Unable to update account."),
      );
    },
  });

  const deleteAccountMutation = useMutation({
    mutationFn: () => deleteAccount(id),

    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["accounts", session?.user.id],
      });

      router.back();
    },

    onError: (mutationError) => {
      // A history-bearing account cannot be hard-deleted: the backend
      // returns a 409 with a clear detail string ("Account with
      // transaction history cannot be deleted. Archive it instead."),
      // which getAccountErrorMessage surfaces as-is instead of the raw
      // "API request failed: 409 {...}" wrapper. This screen never
      // auto-archives on a failed delete, and never attempts to delete
      // ledger rows itself -- the message tells the user to archive
      // instead.
      Alert.alert(
        "Delete account failed",
        getAccountErrorMessage(mutationError, "Unable to delete account."),
      );
    },
  });

  function handleSubmitTransaction() {
    // Guards against duplicate submissions from a double tap while the
    // request is already in flight.
    if (createTransactionMutation.isPending) {
      return;
    }

    const validationError = validateAccountTransactionForm({
      amount,
      description,
    });

    if (validationError) {
      Alert.alert("Invalid transaction", validationError);
      return;
    }

    const trimmedDescription = description.trim();
    const trimmedTransactionDate = transactionDate.trim();

    if (!/^\d{4}-\d{2}-\d{2}$/.test(trimmedTransactionDate)) {
      Alert.alert("Invalid transaction", "Date must use YYYY-MM-DD format.");
      return;
    }

    createTransactionMutation.mutate({
      direction,
      amount: normalizeAccountDecimalAmount(amount),
      transaction_date: trimmedTransactionDate,
      ...(trimmedDescription ? { description: trimmedDescription } : {}),
    });
  }

  function handleArchive() {
    if (archiveMutation.isPending) {
      return;
    }

    Alert.alert(
      "Archive account?",
      "The account and its history remain fully visible in the Archived " +
        "view, but it will no longer accept new transactions until " +
        "reactivated.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Archive",
          onPress: () => archiveMutation.mutate("archived"),
        },
      ],
    );
  }

  function handleReactivate() {
    if (archiveMutation.isPending) {
      return;
    }

    archiveMutation.mutate("active");
  }

  function handleDeleteAccount() {
    if (deleteAccountMutation.isPending) {
      return;
    }

    Alert.alert(
      "Delete account?",
      "This account will be permanently deleted. This is only possible " +
        "if it has no transaction history yet.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: () => deleteAccountMutation.mutate(),
        },
      ],
    );
  }

  if (isAuthLoading || isAccountLoading) {
    return (
      <SafeAreaView style={styles.container}>
        <ActivityIndicator style={styles.loader} />
      </SafeAreaView>
    );
  }

  if (accountError) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.content}>
          <Text style={styles.errorText}>Unable to load account.</Text>
        </View>
      </SafeAreaView>
    );
  }

  if (!account) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.content}>
          <Text style={styles.secondaryText}>Account not found.</Text>

          <Pressable style={styles.button} onPress={() => router.back()}>
            <Text style={styles.buttonText}>Back to accounts</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  const amountValidationError = amount
    ? validateAccountDecimalAmount(amount, "Amount")
    : null;
  const canSubmitTransaction =
    Boolean(amount) &&
    !amountValidationError &&
    Boolean(transactionDate.trim()) &&
    !createTransactionMutation.isPending;

  const isArchived = account.status === "archived";

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
          <Text style={styles.title}>{account.name}</Text>

          <Text style={styles.secondaryText}>{TYPE_LABELS[account.type]}</Text>

          <Text style={styles.secondaryText}>
            {STATUS_LABELS[account.status]}
          </Text>

          <Text style={styles.amount}>
            {account.current_balance} {account.currency}
          </Text>

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

          {isArchived ? (
            <Pressable
              style={styles.archiveButton}
              disabled={archiveMutation.isPending}
              onPress={handleReactivate}
            >
              {archiveMutation.isPending ? (
                <ActivityIndicator />
              ) : (
                <Text style={styles.archiveButtonText}>
                  Reactivate account
                </Text>
              )}
            </Pressable>
          ) : (
            <Pressable
              style={styles.archiveButton}
              disabled={archiveMutation.isPending}
              onPress={handleArchive}
            >
              {archiveMutation.isPending ? (
                <ActivityIndicator />
              ) : (
                <Text style={styles.archiveButtonText}>Archive account</Text>
              )}
            </Pressable>
          )}

          <Pressable
            style={styles.deleteButton}
            disabled={deleteAccountMutation.isPending}
            onPress={handleDeleteAccount}
          >
            {deleteAccountMutation.isPending ? (
              <ActivityIndicator size="small" />
            ) : (
              <Text style={styles.deleteButtonText}>Delete account</Text>
            )}
          </Pressable>

          <Text style={styles.sectionTitle}>Add adjustment</Text>

          {isArchived ? (
            <Text style={styles.noticeText}>
              This account is archived and cannot receive new transactions
              until reactivated.
            </Text>
          ) : null}

          <View style={styles.typeToggleRow}>
            {SUBMITTABLE_DIRECTIONS.map((option) => (
              <Pressable
                key={option}
                accessibilityRole="button"
                accessibilityState={{ selected: direction === option }}
                style={[
                  styles.typeToggleButton,
                  direction === option && styles.typeToggleButtonSelected,
                ]}
                onPress={() => setDirection(option)}
              >
                <Text
                  style={[
                    styles.typeToggleButtonText,
                    direction === option &&
                      styles.typeToggleButtonTextSelected,
                  ]}
                >
                  {option === "credit" ? "Credit" : "Debit"}
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
            <Text style={styles.label}>Transaction date *</Text>

            <TextInput
              style={styles.input}
              placeholder="YYYY-MM-DD"
              value={transactionDate}
              onChangeText={setTransactionDate}
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
            disabled={!canSubmitTransaction || isArchived}
            onPress={handleSubmitTransaction}
            style={[styles.button, styles.formGroup]}
          >
            {createTransactionMutation.isPending ? (
              <ActivityIndicator />
            ) : (
              <Text style={styles.buttonText}>
                {direction === "debit" ? "Add debit" : "Add credit"}
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
                      {KIND_LABELS[transaction.kind]}
                    </Text>

                    <Text style={styles.historyAmount}>
                      {formatTransactionAmount(transaction)}{" "}
                      {account.currency}
                    </Text>
                  </View>

                  {transaction.description ? (
                    <Text style={styles.historyDescription}>
                      {transaction.description}
                    </Text>
                  ) : null}

                  {/* The primary event date is transaction_date (the
                      financial date), never created_at -- see
                      account.types.ts. */}
                  <Text style={styles.historyDate}>
                    {transaction.transaction_date}
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
