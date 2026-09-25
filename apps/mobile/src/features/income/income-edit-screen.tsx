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
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { getApiErrorMessage } from "../../api/api-error-message";
import { useAuth } from "../auth/auth-context";
import { AccountPicker } from "../accounts/account-picker";
import { getAccounts } from "../accounts/account.service";
import { invalidateIncomeQueries } from "./income-cache";
import { IncomeSourcePicker } from "./income-source-picker";
import { normalizeIncomeAmount, validateIncomeForm } from "./income-validation";
import { deleteIncome, getIncome, updateIncome } from "./income.service";
import { styles } from "./income.styles";
import type { Income, IncomeSource, IncomeUpdateInput } from "./income.types";

type IncomeFormState = {
  amount: string;
  currency: string;
  receivedAt: string;
  source: IncomeSource;
  description: string;
  accountId: string | null;
};

// Builds a PATCH payload containing ONLY the fields the user actually
// changed, compared against the Income as last returned by the backend.
// The backend treats an omitted field as "unchanged", so unmodified
// fields are never sent -- in particular account_id, whose presence alone
// means attach/move (UUID) or detach (null).
//
// description has its own rules because the form shows a missing note as
// a blank field, while the API uses null to clear one:
// - untouched field -> omitted;
// - existing note cleared to blank -> null (clears it);
// - still-blank field on an Income without a note -> omitted;
// - non-blank changed value -> the trimmed string.
function buildIncomeUpdatePayload(
  income: Income,
  form: IncomeFormState,
): IncomeUpdateInput {
  const changedFields: IncomeUpdateInput = {};

  const normalizedAmount = normalizeIncomeAmount(form.amount);

  if (normalizedAmount !== income.amount) {
    changedFields.amount = normalizedAmount;
  }

  const normalizedCurrency = form.currency.trim().toUpperCase();

  if (normalizedCurrency !== income.currency) {
    changedFields.currency = normalizedCurrency;
  }

  const normalizedReceivedAt = form.receivedAt.trim();

  if (normalizedReceivedAt !== income.received_at) {
    changedFields.received_at = normalizedReceivedAt;
  }

  if (form.source !== income.source) {
    changedFields.source = form.source;
  }

  if (form.description !== (income.description ?? "")) {
    const trimmedDescription = form.description.trim();
    const nextDescription = trimmedDescription === "" ? null : trimmedDescription;

    if (nextDescription !== income.description) {
      changedFields.description = nextDescription;
    }
  }

  if (form.accountId !== income.account_id) {
    changedFields.account_id = form.accountId;
  }

  return changedFields;
}

export function IncomeEditScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { session, isLoading: isAuthLoading } = useAuth();
  const queryClient = useQueryClient();
  const router = useRouter();

  // There is no GET /income/{id} endpoint -- the Income is resolved from
  // the ["income", userId] list, the same query the Income screen uses.
  const {
    data: income,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["income", session?.user.id],
    queryFn: getIncome,
    enabled: Boolean(session),
    select: (incomeRecords) =>
      incomeRecords.find((candidate) => candidate.id === id),
  });

  const {
    data: accounts = [],
    isLoading: isAccountsLoading,
    error: accountsError,
  } = useQuery({
    queryKey: ["accounts", session?.user.id],
    queryFn: getAccounts,
    enabled: Boolean(session),
  });

  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("EUR");
  const [receivedAt, setReceivedAt] = useState("");
  const [source, setSource] = useState<IncomeSource>("salary");
  const [description, setDescription] = useState("");
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(
    null,
  );

  // Tracks which Income the form fields were last seeded from. `income`
  // arrives asynchronously, so the fields are seeded once it does (and
  // re-seeded if the route ever points at a different id). Mirrors
  // ../accounts/account-edit-screen.tsx's syncedAccountId guard.
  const [syncedIncomeId, setSyncedIncomeId] = useState<string | null>(null);

  if (income && income.id !== syncedIncomeId) {
    setSyncedIncomeId(income.id);
    setAmount(income.amount);
    setCurrency(income.currency);
    setReceivedAt(income.received_at);
    setSource(income.source);
    setDescription(income.description ?? "");
    setSelectedAccountId(income.account_id);
  }

  // previousAccountId travels with each mutation's variables (captured at
  // submit time), so invalidation compares the pre-mutation linkage with
  // the backend's result even after the list query has refetched.
  const updateIncomeMutation = useMutation({
    mutationFn: (variables: {
      payload: IncomeUpdateInput;
      previousAccountId: string | null;
    }) => updateIncome(id, variables.payload),

    onSuccess: async (updatedIncome, variables) => {
      await invalidateIncomeQueries(
        queryClient,
        session?.user.id,
        variables.previousAccountId !== null ||
          updatedIncome.account_id !== null,
      );

      router.back();
    },

    onError: (mutationError) => {
      // Currency mismatch, archived destination, future-dated foreign
      // currency, invalid calendar date, and FX availability are all
      // decided by the backend and surfaced here as its own message.
      Alert.alert(
        "Update income failed",
        getApiErrorMessage(mutationError, "Unable to update income."),
      );
    },
  });

  const deleteIncomeMutation = useMutation({
    mutationFn: (variables: { previousAccountId: string | null }) =>
      deleteIncome(id),

    onSuccess: async (_result, variables) => {
      // The backend removes the linked Account credit itself (cascade);
      // the client only refreshes the affected caches.
      await invalidateIncomeQueries(
        queryClient,
        session?.user.id,
        variables.previousAccountId !== null,
      );

      router.back();
    },

    onError: (mutationError) => {
      Alert.alert(
        "Delete income failed",
        getApiErrorMessage(mutationError, "Unable to delete income."),
      );
    },
  });

  const isMutating =
    updateIncomeMutation.isPending || deleteIncomeMutation.isPending;

  if (isAuthLoading || isLoading) {
    return (
      <SafeAreaView style={styles.container}>
        <ActivityIndicator style={styles.loader} />
      </SafeAreaView>
    );
  }

  if (error) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.content}>
          <Text style={styles.errorText}>Unable to load income.</Text>
        </View>
      </SafeAreaView>
    );
  }

  if (!income) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.content}>
          <Text style={styles.secondaryText}>Income not found.</Text>

          <Pressable style={styles.button} onPress={() => router.back()}>
            <Text style={styles.buttonText}>Back to income</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  const changedFields = buildIncomeUpdatePayload(income, {
    amount,
    currency,
    receivedAt,
    source,
    description,
    accountId: selectedAccountId,
  });

  const hasChanges = Object.keys(changedFields).length > 0;

  function handleSaveChanges() {
    // Guards against duplicate submissions and against sending an empty
    // PATCH, which the backend rejects.
    if (isMutating || !income || !hasChanges) {
      return;
    }

    const validationError = validateIncomeForm({
      amount,
      currency,
      receivedAt,
      source,
      description,
    });

    if (validationError) {
      Alert.alert("Invalid income", validationError);
      return;
    }

    updateIncomeMutation.mutate({
      payload: changedFields,
      previousAccountId: income.account_id,
    });
  }

  function handleDeleteIncome() {
    if (isMutating || !income) {
      return;
    }

    const previousAccountId = income.account_id;

    Alert.alert(
      "Delete income?",
      previousAccountId !== null
        ? "This also removes its credit from the linked account. This cannot be undone."
        : "This cannot be undone.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: () => deleteIncomeMutation.mutate({ previousAccountId }),
        },
      ],
    );
  }

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
          <Text style={styles.title}>Edit income</Text>

          <Text style={styles.helperText}>* Required fields</Text>

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
            <Text style={styles.label}>Currency *</Text>

            <TextInput
              style={styles.input}
              placeholder="EUR"
              value={currency}
              onChangeText={setCurrency}
              autoCapitalize="characters"
              maxLength={3}
            />
          </View>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Received date *</Text>

            <TextInput
              style={styles.input}
              placeholder="YYYY-MM-DD"
              value={receivedAt}
              onChangeText={setReceivedAt}
            />
          </View>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Source *</Text>

            <IncomeSourcePicker value={source} onChange={setSource} />
          </View>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Description</Text>

            <TextInput
              style={[styles.input, styles.inputOptional]}
              placeholder="Optional note"
              value={description}
              onChangeText={setDescription}
              maxLength={500}
            />
          </View>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Account</Text>

            {isAccountsLoading ? (
              <ActivityIndicator style={styles.loader} />
            ) : accountsError ? (
              // Without the Account list the current link cannot be shown
              // or changed safely, so the selection stays as loaded and
              // account_id is simply not part of any PATCH.
              <Text style={styles.errorText}>
                Unable to load accounts. The account link will stay
                unchanged.
              </Text>
            ) : (
              <AccountPicker
                accounts={accounts}
                selectedAccountId={selectedAccountId}
                onChange={setSelectedAccountId}
                currentLinkedAccountId={income.account_id}
              />
            )}

            <Text style={styles.helperText}>
              Optional — a linked account&apos;s currency must match this
              income&apos;s currency. Archived accounts can stay linked but
              cannot be chosen as a new account.
            </Text>
          </View>

          <Pressable
            disabled={isMutating || !hasChanges}
            onPress={handleSaveChanges}
            style={[styles.button, styles.formGroup]}
          >
            {updateIncomeMutation.isPending ? (
              <ActivityIndicator />
            ) : (
              <Text style={styles.buttonText}>Save changes</Text>
            )}
          </Pressable>

          {!hasChanges && !updateIncomeMutation.isPending ? (
            <Text style={styles.helperText}>
              Change a field to enable Save.
            </Text>
          ) : null}

          <Pressable
            disabled={isMutating}
            onPress={handleDeleteIncome}
            style={styles.deleteButton}
          >
            {deleteIncomeMutation.isPending ? (
              <ActivityIndicator />
            ) : (
              <Text style={styles.deleteButtonText}>Delete income</Text>
            )}
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
