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

import { getApiErrorMessage, readApiFailure } from "../../api/api-error-message";
import { getAccounts } from "../accounts/account.service";
import { useAuth } from "../auth/auth-context";
import {
  normalizeGoalDecimalAmount,
  validateGoalDecimalAmount,
} from "./goal-amount-validation";
import { invalidateGoalTransactionQueries } from "./goal-cache";
import {
  GoalPartitionPicker,
  type GoalPartitionPickerOption,
} from "./goal-partition-picker";
import {
  buildContributionAccountOptions,
  buildWithdrawalPartitionOptions,
  getAccountDisplayName,
  getGoalTransactionKindLabel,
} from "./goal-partitions";
import {
  canonicalizeGoalAmount,
  discardGoalTransactionAttempt,
  getGoalTransactionDisplayDate,
  resolveGoalTransactionAttempt,
  toGoalTransactionCreateInput,
  type GoalTransactionAttempt,
} from "./goal-transaction-attempts";
import { mapGoalTransactionFailure } from "./goal-transaction-errors";
import { handleGoalTransactionSuccess } from "./goal-transaction-warning";
import { validateGoalTransactionForm } from "./goal-transaction-validation";
import {
  createGoalTransaction,
  getGoalTransactions,
  getGoals,
} from "./goal.service";
import { styles } from "./goals.styles";
import type {
  Goal,
  GoalStatus,
  GoalTransaction,
  GoalTransactionCreateInput,
} from "./goal.types";

const STATUS_LABELS: Record<GoalStatus, string> = {
  active: "Active",
  completed: "Completed",
  archived: "Archived",
};

// Where a contribution is recorded (VF-020C3): "tracked" keeps the money in
// the Goal only; "reserve" earmarks it against one Account. Presentation
// state of the form, not a backend concept.
type ContributionSource = "tracked" | "reserve";

const RESERVATION_HELPER_TEXT =
  "Reserving earmarks money for this goal. It does not move money out of the account.";

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

  // The full Account list (active and archived) from the shared
  // ["accounts", userId] cache. It supplies reservation capacity for the
  // selector and Account names for allocations and linked history; there is
  // never a per-allocation request. A load failure only degrades names to
  // "Account unavailable" and empties the reservation selector.
  const {
    data: accounts = [],
    isLoading: isAccountsLoading,
    error: accountsError,
  } = useQuery({
    queryKey: ["accounts", session?.user.id],
    queryFn: getAccounts,
    enabled: Boolean(session),
  });

  const [transactionType, setTransactionType] = useState<
    "contribution" | "withdrawal"
  >("contribution");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [contributionSource, setContributionSource] =
    useState<ContributionSource>("tracked");
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(
    null,
  );
  // Explicit withdrawal partition choice. Never preselected: null until the
  // user picks one, and never replaced by another partition automatically.
  const [selectedPartitionKey, setSelectedPartitionKey] = useState<
    string | null
  >(null);

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
    onSuccess: async (transaction, variables) => {
      // The advisory floor warning (backend `warnings`) is presented before
      // the refetch is awaited and never turns this success into an error;
      // see handleGoalTransactionSuccess. Goals, this Goal's history and
      // Goal Progress are always refreshed; Accounts too for a linked
      // operation. A reservation writes no AccountTransaction, so Account
      // history stays untouched. New values always come from a refetch.
      await handleGoalTransactionSuccess({
        response: transaction,
        currency: transaction.currency ?? goal?.currency ?? "",
        resetForm: () => {
          createAttemptsRef.current = [];
          setAmount("");
          setDescription("");
        },
        presentWarning: (title, message) => Alert.alert(title, message),
        invalidate: () =>
          invalidateGoalTransactionQueries(
            queryClient,
            session?.user.id,
            id,
            variables.account_id !== undefined,
          ),
      });
    },

    // `variables` is the exact payload passed to .mutate() for this
    // specific failed call, read here instead of the outer transactionType
    // state so the alert title always matches the request that actually
    // failed, even if the user has since toggled the control. The attempts
    // are deliberately kept: the request may have been committed even
    // though it failed here, so resubmitting the unchanged form must reuse
    // the same key.
    onError: (mutationError, variables) => {
      const isLinked = variables.account_id !== undefined;
      const title = isLinked
        ? variables.type === "withdrawal"
          ? "Release failed"
          : "Reservation failed"
        : variables.type === "withdrawal"
          ? "Withdrawal failed"
          : "Contribution failed";
      const fallback = "Unable to create transaction.";

      // The backend sends no error codes: branch on the status plus the
      // exact detail text and the operation, never on the status alone. A
      // non-HTTP failure (e.g. network) keeps the shared parser's message.
      const failure = readApiFailure(mutationError);
      const handling =
        failure.status === null
          ? null
          : mapGoalTransactionFailure(
              failure,
              { type: variables.type, isLinked },
              fallback,
            );

      Alert.alert(
        title,
        handling ? handling.message : getApiErrorMessage(mutationError, fallback),
      );

      if (handling?.refreshGoals) {
        void queryClient.invalidateQueries({
          queryKey: ["goals", session?.user.id],
        });
      }

      if (handling?.refreshAccounts) {
        void queryClient.invalidateQueries({
          queryKey: ["accounts", session?.user.id],
        });
      }

      if (handling?.clearSelectedAccount) {
        setSelectedAccountId(null);
      }

      // Only after the conflict has been presented: the stale key must not
      // be reused, so the next submit of this form starts a new logical
      // request.
      if (handling?.discardAttempt && variables.client_request_id) {
        createAttemptsRef.current = discardGoalTransactionAttempt(
          createAttemptsRef.current,
          variables.client_request_id,
        );
      }
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

    const type = resolveSelectedTransactionType(goal.status, transactionType);
    const accountId = resolveSubmitAccountId(goal, type);

    if (accountId === undefined) {
      Alert.alert(
        "Invalid transaction",
        type === "withdrawal"
          ? "Select what to withdraw from."
          : "Select an account to reserve from.",
      );
      return;
    }

    const trimmedDescription = description.trim();

    const { attempt, attempts } = resolveGoalTransactionAttempt(
      createAttemptsRef.current,
      {
        goalId: goal.id,
        type,
        amount: canonicalizeGoalAmount(normalizeGoalDecimalAmount(amount)),
        description: trimmedDescription ? trimmedDescription : null,
        accountId,
      },
      () => Crypto.randomUUID(),
    );

    createAttemptsRef.current = attempts;
    createTransactionMutation.mutate(toGoalTransactionCreateInput(attempt));
  }

  // Resolves the partition of the form against the CURRENT data: null =
  // tracked, a string = linked Account, undefined = nothing valid selected.
  // A selection that is no longer offered (an Account archived or a
  // partition emptied since it was picked) resolves to undefined and is
  // never swapped for another partition.
  function resolveSubmitAccountId(
    currentGoal: Goal,
    type: "contribution" | "withdrawal",
  ): string | null | undefined {
    if (type === "withdrawal") {
      return buildWithdrawalPartitionOptions(currentGoal, accounts).find(
        (option) => option.key === selectedPartitionKey,
      )?.accountId;
    }

    if (contributionSource === "tracked") {
      return null;
    }

    return buildContributionAccountOptions(accounts, currentGoal.currency).find(
      (option) => option.accountId === selectedAccountId,
    )?.accountId;
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
  const availableTransactionTypes = getSubmittableTransactionTypes(goal.status);
  const selectedTransactionType = resolveSelectedTransactionType(
    goal.status,
    transactionType,
  );

  const contributionAccountOptions = buildContributionAccountOptions(
    accounts,
    goal.currency,
  );
  const withdrawalPartitionOptions = buildWithdrawalPartitionOptions(
    goal,
    accounts,
  );
  const selectedContributionAccount = contributionAccountOptions.find(
    (option) => option.accountId === selectedAccountId,
  );
  const selectedWithdrawalPartition = withdrawalPartitionOptions.find(
    (option) => option.key === selectedPartitionKey,
  );
  const isReserving =
    selectedTransactionType === "contribution" &&
    contributionSource === "reserve";

  // A required choice that is not (or no longer) available blocks only the
  // submit button; capacity and partition amounts are context and never
  // disable it - the backend stays the authority.
  const hasRequiredSelection =
    selectedTransactionType === "withdrawal"
      ? Boolean(selectedWithdrawalPartition)
      : !isReserving || Boolean(selectedContributionAccount);
  const canSubmitTransaction =
    Boolean(amount) &&
    !amountValidationError &&
    hasRequiredSelection &&
    !createTransactionMutation.isPending;

  const contributionPickerOptions: GoalPartitionPickerOption[] =
    contributionAccountOptions.map((option) => ({
      key: option.accountId,
      label: option.label,
      detail: `Available to reserve: ${option.reservableAmount} ${option.currency}${
        option.hasNoCapacity ? " — No capacity" : ""
      }`,
    }));
  const withdrawalPickerOptions: GoalPartitionPickerOption[] =
    withdrawalPartitionOptions.map((option) => ({
      key: option.key,
      label: option.label,
      detail: `${option.amount} ${goal.currency}`,
    }));

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
            Tracked: {goal.tracked_amount} {goal.currency}
          </Text>

          <Text style={styles.secondaryText}>
            Reserved in accounts: {goal.linked_amount} {goal.currency}
          </Text>

          {goal.allocations.map((allocation) => (
            <Text key={allocation.account_id} style={styles.secondaryText}>
              {getAccountDisplayName(allocation.account_id, accounts)} —{" "}
              {allocation.amount} {goal.currency}
            </Text>
          ))}

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
                      {option === "withdrawal" ? "Withdrawal" : "Contribution"}
                    </Text>
                  </Pressable>
                ))}
              </View>
            </>
          )}

          {selectedTransactionType === "contribution" ? (
            <View style={styles.formGroup}>
              <Text style={styles.label}>Where to record it</Text>

              <View style={styles.typeToggleRow}>
                {(["tracked", "reserve"] as ContributionSource[]).map(
                  (option) => (
                    <Pressable
                      key={option}
                      accessibilityState={{
                        selected: contributionSource === option,
                      }}
                      style={[
                        styles.typeToggleButton,
                        contributionSource === option &&
                          styles.typeToggleButtonSelected,
                      ]}
                      onPress={() => setContributionSource(option)}
                    >
                      <Text
                        style={[
                          styles.typeToggleButtonText,
                          contributionSource === option &&
                            styles.typeToggleButtonTextSelected,
                        ]}
                      >
                        {option === "tracked"
                          ? "Tracked (not tied to an account)"
                          : "Reserve from account"}
                      </Text>
                    </Pressable>
                  ),
                )}
              </View>

              {isReserving ? (
                <>
                  <Text style={styles.helperText}>
                    {RESERVATION_HELPER_TEXT}
                  </Text>

                  {accountsError ? (
                    <Text style={styles.errorText}>
                      Unable to load accounts.
                    </Text>
                  ) : isAccountsLoading ? (
                    <ActivityIndicator style={styles.loader} />
                  ) : contributionAccountOptions.length === 0 ? (
                    <Text style={styles.secondaryText}>
                      No active {goal.currency} account to reserve from.
                    </Text>
                  ) : (
                    <View style={styles.formGroup}>
                      <GoalPartitionPicker
                        title="Reserve from account"
                        placeholder="Select an account"
                        options={contributionPickerOptions}
                        selectedKey={selectedContributionAccount?.accountId ?? null}
                        onChange={setSelectedAccountId}
                      />
                    </View>
                  )}

                  {selectedContributionAccount ? (
                    <Text style={styles.helperText}>
                      Available to reserve:{" "}
                      {selectedContributionAccount.reservableAmount}{" "}
                      {selectedContributionAccount.currency}
                      {selectedContributionAccount.hasNoCapacity
                        ? " — No capacity"
                        : ""}
                    </Text>
                  ) : null}
                </>
              ) : null}
            </View>
          ) : (
            <View style={styles.formGroup}>
              <Text style={styles.label}>Withdraw from</Text>

              {withdrawalPartitionOptions.length === 0 ? (
                <Text style={styles.secondaryText}>Nothing to withdraw</Text>
              ) : (
                <GoalPartitionPicker
                  title="Withdraw from"
                  placeholder="Select what to withdraw from"
                  options={withdrawalPickerOptions}
                  selectedKey={selectedWithdrawalPartition?.key ?? null}
                  onChange={setSelectedPartitionKey}
                />
              )}

              {selectedWithdrawalPartition ? (
                <Text style={styles.helperText}>
                  Available in this partition: {selectedWithdrawalPartition.amount}{" "}
                  {goal.currency}
                </Text>
              ) : null}
            </View>
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
                  : isReserving
                    ? "Reserve from account"
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
                      {getGoalTransactionKindLabel(transaction)}
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

                  {transaction.account_id !== null ? (
                    <Text style={styles.historyDescription}>
                      Account:{" "}
                      {getAccountDisplayName(transaction.account_id, accounts)}
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
