import { useState } from "react";
import { Link } from "expo-router";
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

import { getApiErrorMessage } from "../../api/api-error-message";
import { AccountPicker } from "../accounts/account-picker";
import { getAccounts } from "../accounts/account.service";
import { useAuth } from "../auth/auth-context";
import { getCategories } from "../categories/category.service";
import { invalidateExpenseQueries } from "./expense-cache";
import {
  normalizeExpenseAmount,
  validateExpenseForm,
} from "./expense-validation";
import {
  createExpense,
  getExpenses,
} from "./expense.service";
import type { ExpenseCreateInput } from "./expense.types";
import { styles } from "./expenses.styles";

function getCurrentLocalDate(): string {
  const now = new Date();

  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");

  return `${year}-${month}-${day}`;
}

export function ExpensesScreen() {
  const { session } = useAuth();
  const queryClient = useQueryClient();

  const [title, setTitle] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("EUR");
  const [expenseDate, setExpenseDate] = useState(
    getCurrentLocalDate,
  );
  const [description, setDescription] = useState("");
  const [selectedCategoryId, setSelectedCategoryId] =
  useState<string | null>(null);
  const [selectedAccountId, setSelectedAccountId] =
    useState<string | null>(null);

  // Compact "tap to open" picker replaces the previous permanently-rendered
  // vertical list of category Buttons (see budget-create-screen.tsx / VF-007D
  // for the pattern this mirrors).
  const [isCategoryPickerVisible, setIsCategoryPickerVisible] =
    useState(false);

  const {
    data: expenses = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["expenses", session?.user.id],
    queryFn: getExpenses,
    enabled: Boolean(session),
  });

  const {
    data: categories = [],
    isLoading: isCategoriesLoading,
    error: categoriesError,
  } = useQuery({
    queryKey: ["categories", session?.user.id],
    queryFn: getCategories,
    enabled: Boolean(session),
  });

  // Same query key/data as the Accounts screen -- no separate Account
  // request path. Used only to offer link destinations, never to compute
  // or display balances.
  const {
    data: accounts = [],
    isLoading: isAccountsLoading,
    error: accountsError,
  } = useQuery({
    queryKey: ["accounts", session?.user.id],
    queryFn: getAccounts,
    enabled: Boolean(session),
  });

  const selectedCategoryLabel =
    selectedCategoryId === null
      ? "Uncategorized"
      : (categories.find((category) => category.id === selectedCategoryId)
          ?.name ?? "Uncategorized");

  const createExpenseMutation = useMutation({
    mutationFn: createExpense,

    onSuccess: async (createdExpense) => {
      // Date, category, and currency stay for quick repeated entry; the
      // Account resets to "No account" because a ledger link is
      // financially significant and must never carry over to the next
      // Expense by accident.
      setTitle("");
      setAmount("");
      setDescription("");
      setSelectedAccountId(null);

      // The backend's returned account_id (not the already-reset form
      // state) decides whether an Account ledger was touched.
      await invalidateExpenseQueries(
        queryClient,
        session?.user.id,
        createdExpense.account_id !== null,
      );
    },

    onError: (mutationError) => {
      Alert.alert(
        "Create expense failed",
        getApiErrorMessage(mutationError, "Unable to create expense."),
      );
    },
  });

  function handleCreateExpense() {
    // Guards against duplicate submissions from a double tap while the
    // request is already in flight.
    if (createExpenseMutation.isPending) {
      return;
    }

    const validationError = validateExpenseForm({
      title,
      amount,
      currency,
      expenseDate,
      description,
    });

    if (validationError) {
      Alert.alert("Invalid expense", validationError);
      return;
    }

    const payload: ExpenseCreateInput = {
      category_id: selectedCategoryId,
      title: title.trim(),
      amount: normalizeExpenseAmount(amount),
      currency: currency.trim().toUpperCase(),
      expense_date: expenseDate.trim(),
      description: description.trim() || null,
    };

    // "No account" omits account_id entirely -> an unlinked Expense.
    if (selectedAccountId !== null) {
      payload.account_id = selectedAccountId;
    }

    createExpenseMutation.mutate(payload);
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
          <Text style={styles.title}>Expenses</Text>

          <Text style={styles.sectionTitle}>Create expense</Text>

          <Text style={styles.helperText}>* Required fields</Text>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Title *</Text>

            <TextInput
              style={styles.input}
              placeholder="e.g. Coffee"
              value={title}
              onChangeText={setTitle}
            />
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
            <Text style={styles.label}>Category</Text>

            {isCategoriesLoading ? (
              <ActivityIndicator style={styles.loader} />
            ) : categoriesError ? (
              <Text style={styles.errorText}>Unable to load categories.</Text>
            ) : (
              <Pressable
                style={styles.selectControl}
                onPress={() => setIsCategoryPickerVisible(true)}
              >
                <Text style={styles.selectControlText}>
                  {selectedCategoryLabel}
                </Text>

                <Text style={styles.selectControlChevron}>▾</Text>
              </Pressable>
            )}
          </View>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Date *</Text>

            <TextInput
              style={styles.input}
              placeholder="YYYY-MM-DD"
              value={expenseDate}
              onChangeText={setExpenseDate}
            />
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

            {/* A failed background refetch keeps the last loaded list, so
                the notice is shown only when no Accounts are available at
                all -- the picker (and any current selection) otherwise stays
                visible, and nothing is ever linked invisibly. */}
            {isAccountsLoading ? (
              <ActivityIndicator style={styles.loader} />
            ) : accountsError && accounts.length === 0 ? (
              <Text style={styles.errorText}>
                Unable to load accounts. You can still add this expense
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
              expense&apos;s currency.
            </Text>
          </View>

          <Pressable
            disabled={createExpenseMutation.isPending}
            onPress={handleCreateExpense}
            style={[styles.button, styles.formGroup]}
          >
            {createExpenseMutation.isPending ? (
              <ActivityIndicator />
            ) : (
              <Text style={styles.buttonText}>Add expense</Text>
            )}
          </Pressable>

          <Text style={styles.listSectionTitle}>Recent expenses</Text>

          {isLoading ? (
            <ActivityIndicator style={styles.loader} />
          ) : error ? (
            <Text style={styles.errorText}>Unable to load expenses.</Text>
          ) : expenses.length === 0 ? (
            <Text style={styles.secondaryText}>No expenses yet.</Text>
          ) : (
            <View style={styles.list}>
              {expenses.map((expense) => (
                <Link
                  key={expense.id}
                  href={{
                    pathname: "/expenses/[id]",
                    params: { id: expense.id },
                  }}
                  asChild
                >
                  <Pressable style={styles.card}>
                    <Text style={styles.name}>{expense.title}</Text>

                    <Text style={styles.amount}>
                      {expense.amount} {expense.currency}
                    </Text>

                    <Text style={styles.secondaryText}>
                      {expense.expense_date}
                    </Text>
                  </Pressable>
                </Link>
              ))}
            </View>
          )}
        </ScrollView>
      </KeyboardAvoidingView>

      <Modal
        visible={isCategoryPickerVisible}
        transparent
        animationType="slide"
        onRequestClose={() => setIsCategoryPickerVisible(false)}
      >
        <Pressable
          style={styles.modalOverlay}
          onPress={() => setIsCategoryPickerVisible(false)}
        >
          <Pressable
            style={styles.modalSheet}
            onPress={(event) => event.stopPropagation()}
          >
            <Text style={styles.modalTitle}>Select category</Text>

            <ScrollView style={styles.modalOptionList}>
              <Pressable
                style={styles.modalOption}
                onPress={() => {
                  setSelectedCategoryId(null);
                  setIsCategoryPickerVisible(false);
                }}
              >
                <Text
                  style={[
                    styles.modalOptionText,
                    selectedCategoryId === null &&
                      styles.modalOptionSelectedText,
                  ]}
                >
                  {selectedCategoryId === null
                    ? "✓ Uncategorized"
                    : "Uncategorized"}
                </Text>
              </Pressable>

              {categories.map((category) => (
                <Pressable
                  key={category.id}
                  style={styles.modalOption}
                  onPress={() => {
                    setSelectedCategoryId(category.id);
                    setIsCategoryPickerVisible(false);
                  }}
                >
                  <Text
                    style={[
                      styles.modalOptionText,
                      selectedCategoryId === category.id &&
                        styles.modalOptionSelectedText,
                    ]}
                  >
                    {selectedCategoryId === category.id
                      ? `✓ ${category.name}`
                      : category.name}
                  </Text>
                </Pressable>
              ))}
            </ScrollView>

            <Pressable
              style={styles.modalCloseButton}
              onPress={() => setIsCategoryPickerVisible(false)}
            >
              <Text style={styles.buttonText}>Close</Text>
            </Pressable>
          </Pressable>
        </Pressable>
      </Modal>
    </SafeAreaView>
  );
}
