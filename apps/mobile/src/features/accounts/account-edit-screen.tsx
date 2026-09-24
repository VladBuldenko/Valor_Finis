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
import { getAccountErrorMessage } from "./account-error-message";
import { validateAccountEditForm } from "./account-edit-validation";
import { getAccounts, updateAccount } from "./account.service";
import { styles } from "./accounts.styles";
import type { AccountType, AccountUpdateInput } from "./account.types";

const ACCOUNT_TYPES: AccountType[] = ["checking", "savings", "cash"];

const TYPE_LABELS: Record<AccountType, string> = {
  checking: "Checking",
  savings: "Savings",
  cash: "Cash",
};

export function AccountEditScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { session, isLoading: isAuthLoading } = useAuth();
  const queryClient = useQueryClient();
  const router = useRouter();

  // There is no GET /accounts/{id} endpoint -- the account is resolved
  // from the already-fetched ["accounts", userId] list, the same query key
  // and data the Accounts screen and Create Account's cache invalidation
  // use. Mirrors ../goals/goal-edit-screen.tsx's resolution pattern exactly.
  const {
    data: account,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["accounts", session?.user.id],
    queryFn: getAccounts,
    enabled: Boolean(session),
    select: (accounts) => accounts.find((candidate) => candidate.id === id),
  });

  const [name, setName] = useState("");
  const [type, setType] = useState<AccountType>("checking");
  const [currency, setCurrency] = useState("EUR");

  const [isTypePickerVisible, setIsTypePickerVisible] = useState(false);

  // Tracks which account the form fields were last synced from. `account`
  // arrives asynchronously (TanStack Query), so it is undefined on first
  // render and only becomes available later -- the fields must be seeded
  // once it does. Mirrors ../goals/goal-edit-screen.tsx's syncedGoalId guard.
  const [syncedAccountId, setSyncedAccountId] = useState<string | null>(null);

  if (account && account.id !== syncedAccountId) {
    setSyncedAccountId(account.id);
    setName(account.name);
    setType(account.type);
    setCurrency(account.currency);
  }

  const updateAccountMutation = useMutation({
    mutationFn: (payload: AccountUpdateInput) => updateAccount(id, payload),

    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["accounts", session?.user.id],
      });

      router.back();
    },

    onError: (mutationError) => {
      // A currency change on an account that already has transaction
      // history is rejected by the backend with a clear 409 detail string
      // ("Account currency cannot be changed after transaction history
      // exists."), which getAccountErrorMessage surfaces as-is. This
      // screen never infers currency mutability from locally-loaded
      // history -- the backend remains the sole authority.
      Alert.alert(
        "Update account failed",
        getAccountErrorMessage(mutationError, "Unable to update account."),
      );
    },
  });

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

  // Builds a PATCH payload containing only the fields the user actually
  // changed, matching the backend's exclude_unset semantics: an omitted
  // field stays unchanged, so unmodified fields must never be sent. status
  // is never part of this payload -- Archive/Reactivate is a separate
  // lifecycle action on Account detail (see account-detail-screen.tsx).
  const normalizedName = name.trim();
  const normalizedCurrency = currency.trim().toUpperCase();

  const changedFields: AccountUpdateInput = {};

  if (normalizedName !== account.name) {
    changedFields.name = normalizedName;
  }

  if (type !== account.type) {
    changedFields.type = type;
  }

  if (normalizedCurrency !== account.currency) {
    changedFields.currency = normalizedCurrency;
  }

  const hasChanges = Object.keys(changedFields).length > 0;

  function handleSaveChanges() {
    // Guards against duplicate submissions from a double tap while the
    // request is already in flight, and against sending an empty PATCH the
    // backend would reject.
    if (updateAccountMutation.isPending || !hasChanges) {
      return;
    }

    const validationError = validateAccountEditForm({ name, type, currency });

    if (validationError) {
      Alert.alert("Invalid account", validationError);
      return;
    }

    updateAccountMutation.mutate(changedFields);
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
          <Text style={styles.title}>Edit account</Text>

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

            <Text style={styles.helperText}>
              Cannot be changed once this account has any transaction
              history.
            </Text>
          </View>

          <Pressable
            disabled={updateAccountMutation.isPending || !hasChanges}
            onPress={handleSaveChanges}
            style={[styles.button, styles.formGroup]}
          >
            {updateAccountMutation.isPending ? (
              <ActivityIndicator />
            ) : (
              <Text style={styles.buttonText}>Save changes</Text>
            )}
          </Pressable>

          {!hasChanges && !updateAccountMutation.isPending ? (
            <Text style={styles.helperText}>
              Change a field to enable Save.
            </Text>
          ) : null}
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
