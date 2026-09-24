import { useState } from "react";
import { useRouter } from "expo-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Modal,
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
  isZeroDecimalAmount,
  normalizeAccountDecimalAmount,
} from "./account-amount-validation";
import { getAccountErrorMessage } from "./account-error-message";
import { validateAccountForm } from "./account-validation";
import { createAccount } from "./account.service";
import { styles } from "./accounts.styles";
import type { AccountCreateInput, AccountType } from "./account.types";

const ACCOUNT_TYPES: AccountType[] = ["checking", "savings", "cash"];

const TYPE_LABELS: Record<AccountType, string> = {
  checking: "Checking",
  savings: "Savings",
  cash: "Cash",
};

export function AccountCreateScreen() {
  const { session } = useAuth();
  const queryClient = useQueryClient();
  const router = useRouter();

  const [name, setName] = useState("");
  const [type, setType] = useState<AccountType>("checking");
  const [currency, setCurrency] = useState("EUR");
  const [openingBalance, setOpeningBalance] = useState("");
  const [openingBalanceDate, setOpeningBalanceDate] = useState("");

  const [isTypePickerVisible, setIsTypePickerVisible] = useState(false);

  const createAccountMutation = useMutation({
    mutationFn: createAccount,

    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["accounts", session?.user.id],
      });

      router.back();
    },

    onError: (mutationError) => {
      Alert.alert(
        "Create account failed",
        getAccountErrorMessage(mutationError, "Unable to create account."),
      );
    },
  });

  function handleCreateAccount() {
    // Guards against duplicate submissions from a double tap while the
    // request is already in flight.
    if (createAccountMutation.isPending) {
      return;
    }

    const validationError = validateAccountForm({
      name,
      type,
      currency,
      openingBalance,
      openingBalanceDate,
    });

    if (validationError) {
      Alert.alert("Invalid account", validationError);
      return;
    }

    const normalizedName = name.trim();
    const normalizedCurrency = currency.trim().toUpperCase();
    const normalizedOpeningBalance = normalizeAccountDecimalAmount(
      openingBalance,
    );
    const trimmedOpeningBalanceDate = openingBalanceDate.trim();

    const payload: AccountCreateInput = {
      name: normalizedName,
      type,
      currency: normalizedCurrency,
    };

    // Zero/empty opening balance means "no starting balance" -- the
    // backend creates no ledger transaction for it either way, so the
    // field (and its date, which the backend ignores whenever
    // opening_balance is omitted or zero) is omitted from the payload
    // entirely rather than sent as "0.00". This detection stays
    // string-based throughout (isZeroDecimalAmount), never Number/parseFloat.
    if (normalizedOpeningBalance && !isZeroDecimalAmount(normalizedOpeningBalance)) {
      payload.opening_balance = normalizedOpeningBalance;

      // A blank date alongside a real non-zero opening balance is left
      // omitted rather than filled in with today's date client-side --
      // the backend already documents and implements exactly that
      // fallback ("defaults to today when opening_balance is non-zero and
      // this is omitted"), so duplicating that date math here would be
      // redundant and could drift from the backend's own definition of
      // "today" (timezone/server-clock differences).
      if (trimmedOpeningBalanceDate) {
        payload.opening_balance_date = trimmedOpeningBalanceDate;
      }
    }

    createAccountMutation.mutate(payload);
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
          <Text style={styles.title}>Add account</Text>

          <Text style={styles.helperText}>* Required fields</Text>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Name *</Text>

            <TextInput
              style={styles.input}
              placeholder="e.g. Main Checking"
              value={name}
              onChangeText={setName}
            />
          </View>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Type *</Text>

            <Pressable
              style={styles.selectControl}
              onPress={() => setIsTypePickerVisible(true)}
            >
              <Text style={styles.selectControlText}>
                {TYPE_LABELS[type]}
              </Text>

              <Text style={styles.selectControlChevron}>▾</Text>
            </Pressable>
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
            <Text style={styles.label}>Opening balance</Text>

            <TextInput
              style={[styles.input, styles.inputOptional]}
              placeholder="0.00"
              value={openingBalance}
              onChangeText={setOpeningBalance}
              keyboardType="numbers-and-punctuation"
            />

            <Text style={styles.helperText}>
              Optional — a positive amount records a starting credit, a
              negative amount (e.g. -150.00) records a starting debit. Leave
              blank or zero for no opening transaction.
            </Text>
          </View>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Opening balance date</Text>

            <TextInput
              style={[styles.input, styles.inputOptional]}
              placeholder="YYYY-MM-DD"
              value={openingBalanceDate}
              onChangeText={setOpeningBalanceDate}
            />

            <Text style={styles.helperText}>
              Optional — only used with a non-zero opening balance;
              defaults to today when left blank.
            </Text>
          </View>

          <Pressable
            disabled={createAccountMutation.isPending}
            onPress={handleCreateAccount}
            style={[styles.button, styles.formGroup]}
          >
            {createAccountMutation.isPending ? (
              <ActivityIndicator />
            ) : (
              <Text style={styles.buttonText}>Save account</Text>
            )}
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>

      <Modal
        visible={isTypePickerVisible}
        transparent
        animationType="slide"
        onRequestClose={() => setIsTypePickerVisible(false)}
      >
        <Pressable
          style={styles.modalOverlay}
          onPress={() => setIsTypePickerVisible(false)}
        >
          <Pressable
            style={styles.modalSheet}
            onPress={(event) => event.stopPropagation()}
          >
            <Text style={styles.modalTitle}>Select type</Text>

            <View style={styles.modalOptionList}>
              {ACCOUNT_TYPES.map((option) => (
                <Pressable
                  key={option}
                  style={styles.modalOption}
                  onPress={() => {
                    setType(option);
                    setIsTypePickerVisible(false);
                  }}
                >
                  <Text
                    style={[
                      styles.modalOptionText,
                      type === option && styles.modalOptionSelectedText,
                    ]}
                  >
                    {type === option
                      ? `✓ ${TYPE_LABELS[option]}`
                      : TYPE_LABELS[option]}
                  </Text>
                </Pressable>
              ))}
            </View>

            <Pressable
              style={styles.modalCloseButton}
              onPress={() => setIsTypePickerVisible(false)}
            >
              <Text style={styles.buttonText}>Close</Text>
            </Pressable>
          </Pressable>
        </Pressable>
      </Modal>
    </SafeAreaView>
  );
}
