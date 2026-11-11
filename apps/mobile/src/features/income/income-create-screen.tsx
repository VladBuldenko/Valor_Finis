import { useRef, useState } from "react";
import * as Crypto from "expo-crypto";
import { useRouter } from "expo-router";
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

import { describeCreateFailure } from "../../api/create-failure";
import {
  createSubmitGuard,
  resolveCreateAttempt,
  type CreateAttempt,
} from "../../lib/create-attempts";
import { LoadingState, RetryAction } from "../../components/query-states";
import { useAuth } from "../auth/auth-context";
import { useRulesEvaluation } from "../financial-rules/rules-evaluation-provider";
import { AccountPicker } from "../accounts/account-picker";
import { getAccounts } from "../accounts/account.service";
import { invalidateIncomeQueries } from "./income-cache";
import {
  incomePayloadKey,
  toIncomeCreateInput,
  type IncomeCreatePayload,
} from "./income-create-attempt";
import { IncomeSourcePicker } from "./income-source-picker";
import { normalizeIncomeAmount, validateIncomeForm } from "./income-validation";
import { createIncome } from "./income.service";
import { styles } from "./income.styles";
import type { IncomeSource } from "./income.types";

// Returns the user's LOCAL calendar date as YYYY-MM-DD. Deliberately not
// toISOString(), which converts to UTC first and can yield the previous/
// next calendar day near midnight in non-UTC timezones.
function getTodayLocalDate(): string {
  const now = new Date();

  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");

  return `${year}-${month}-${day}`;
}

export function IncomeCreateScreen() {
  const { session } = useAuth();
  const queryClient = useQueryClient();
  const { request: requestRulesEvaluation } = useRulesEvaluation();
  const router = useRouter();

  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("EUR");
  const [receivedAt, setReceivedAt] = useState(getTodayLocalDate);
  const [source, setSource] = useState<IncomeSource>("salary");
  const [description, setDescription] = useState("");
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(
    null,
  );

  // Create idempotency (VF-MVP-CORE-002). The attempts of this form instance
  // are kept across failed submissions, so a retry of the same payload reuses
  // its client_request_id (the backend then replays the saved Income instead of
  // adding a second one); they are cleared after a success and discarded when
  // the screen closes. Refs, not state: they never affect rendering and are
  // only read in event handlers. The guard is synchronous, unlike isPending,
  // which only turns true after a re-render.
  const createAttemptsRef = useRef<CreateAttempt<IncomeCreatePayload>[]>([]);
  const submitGuardRef = useRef(createSubmitGuard());

  const {
    data: accounts = [],
    isLoading: isAccountsLoading,
    error: accountsError,
    refetch: refetchAccounts,
    isFetching: isAccountsFetching,
  } = useQuery({
    queryKey: ["accounts", session?.user.id],
    queryFn: getAccounts,
    enabled: Boolean(session),
  });

  const createIncomeMutation = useMutation({
    mutationFn: createIncome,

    // 201 (new) and 200 (exact replay of an earlier, possibly lost, attempt)
    // are the same success: the body is the Income's current state either way.
    onSuccess: async (createdIncome) => {
      createAttemptsRef.current = [];

      // The backend's returned account_id (not the form's selection) is
      // what decides whether an Account ledger was actually touched.
      await invalidateIncomeQueries(
        queryClient,
        session?.user.id,
        createdIncome.account_id !== null,
      );

      // New income may be due for rules: ask the evaluation host (debounced;
      // a no-op when signed out). Never blocks or fails the create.
      requestRulesEvaluation("income_recorded");

      router.back();
    },

    // The attempts are deliberately kept: the request may have been committed
    // even though it failed here, so resubmitting the unchanged form must reuse
    // the same key. Only a key the backend rejected as belonging to a different
    // request is dropped.
    onError: (mutationError) => {
      const failure = describeCreateFailure(
        mutationError,
        "income",
        "Unable to create income.",
      );

      if (failure.discardAttempt) {
        createAttemptsRef.current = [];
      }

      Alert.alert(failure.title, failure.message);
    },

    onSettled: () => {
      submitGuardRef.current.release();
    },
  });

  function handleCreateIncome() {
    // Guards against duplicate submissions from a double tap while the
    // request is already in flight.
    if (createIncomeMutation.isPending || submitGuardRef.current.isBusy()) {
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

    const payload: IncomeCreatePayload = {
      amount: normalizeIncomeAmount(amount),
      currency: currency.trim().toUpperCase(),
      received_at: receivedAt.trim(),
      source,
    };

    // A blank note is omitted rather than sent as "" or whitespace.
    const trimmedDescription = description.trim();

    if (trimmedDescription) {
      payload.description = trimmedDescription;
    }

    // "No account" omits account_id entirely -> an unlinked Income.
    if (selectedAccountId !== null) {
      payload.account_id = selectedAccountId;
    }

    // Entered only after validation, so a rejected form never blocks the next
    // tap; released by onSettled.
    if (!submitGuardRef.current.tryEnter()) {
      return;
    }

    try {
      const { attempt, attempts } = resolveCreateAttempt(
        createAttemptsRef.current,
        session?.user.id ?? "",
        incomePayloadKey(payload),
        payload,
        () => Crypto.randomUUID(),
      );

      createAttemptsRef.current = attempts;
      createIncomeMutation.mutate(toIncomeCreateInput(attempt));
    } catch (error) {
      // Nothing was sent (onSettled will not run), so the guard must not stay held.
      submitGuardRef.current.release();
      throw error;
    }
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
          <Text style={styles.title}>Add income</Text>

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
              <LoadingState what="accounts" />
            ) : accountsError ? (
              <>
            <Text style={styles.errorText}>
                Unable to load accounts. You can still add this income
                without an account.
              </Text>
            <RetryAction what="accounts" retrying={isAccountsFetching} onRetry={() => void refetchAccounts()} />
          </>
            ) : (
              <AccountPicker
                accounts={accounts}
                selectedAccountId={selectedAccountId}
                onChange={setSelectedAccountId}
              />
            )}

            <Text style={styles.helperText}>
              Optional — a linked account&apos;s currency must match this
              income&apos;s currency.
            </Text>
          </View>

          <Pressable
            disabled={createIncomeMutation.isPending}
            onPress={handleCreateIncome}
            style={[styles.button, styles.formGroup]}
          >
            {createIncomeMutation.isPending ? (
              <ActivityIndicator />
            ) : (
              <Text style={styles.buttonText}>Save income</Text>
            )}
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
