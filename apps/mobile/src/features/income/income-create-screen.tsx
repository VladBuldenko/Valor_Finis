import { useState } from "react";
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

import { getApiErrorMessage } from "../../api/api-error-message";
import { useAuth } from "../auth/auth-context";
import { AccountPicker } from "../accounts/account-picker";
import { getAccounts } from "../accounts/account.service";
import { invalidateIncomeQueries } from "./income-cache";
import { IncomeSourcePicker } from "./income-source-picker";
import { normalizeIncomeAmount, validateIncomeForm } from "./income-validation";
import { createIncome } from "./income.service";
import { styles } from "./income.styles";
import type { IncomeCreateInput, IncomeSource } from "./income.types";

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
  const router = useRouter();

  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("EUR");
  const [receivedAt, setReceivedAt] = useState(getTodayLocalDate);
  const [source, setSource] = useState<IncomeSource>("salary");
  const [description, setDescription] = useState("");
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(
    null,
  );

  const {
    data: accounts = [],
    isLoading: isAccountsLoading,
    error: accountsError,
  } = useQuery({
    queryKey: ["accounts", session?.user.id],
    queryFn: getAccounts,
    enabled: Boolean(session),
  });

  const createIncomeMutation = useMutation({
    mutationFn: createIncome,

    onSuccess: async (createdIncome) => {
      // The backend's returned account_id (not the form's selection) is
      // what decides whether an Account ledger was actually touched.
      await invalidateIncomeQueries(
        queryClient,
        session?.user.id,
        createdIncome.account_id !== null,
      );

      router.back();
    },

    onError: (mutationError) => {
      Alert.alert(
        "Create income failed",
        getApiErrorMessage(mutationError, "Unable to create income."),
      );
    },
  });

  function handleCreateIncome() {
    // Guards against duplicate submissions from a double tap while the
    // request is already in flight.
    if (createIncomeMutation.isPending) {
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

    const payload: IncomeCreateInput = {
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

    createIncomeMutation.mutate(payload);
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
              <ActivityIndicator style={styles.loader} />
            ) : accountsError ? (
              <Text style={styles.errorText}>
                Unable to load accounts. You can still add this income
                without an account.
              </Text>
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
