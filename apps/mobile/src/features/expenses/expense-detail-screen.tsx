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
  Button,
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
  deleteExpense,
  getExpenses,
  updateExpense,
} from "./expense.service";
import type { Expense, ExpenseUpdateInput } from "./expense.types";
import { styles } from "./expenses.styles";

type ExpenseFormState = {
  categoryId: string | null;
  title: string;
  amount: string;
  currency: string;
  expenseDate: string;
  description: string;
  accountId: string | null;
};

// Builds a PATCH payload containing ONLY the fields the user actually
// changed, compared against the Expense as last returned by the backend.
// The backend treats an omitted field as "unchanged", so unmodified fields
// are never sent -- in particular account_id, whose presence alone means
// attach/move (UUID) or detach (null), and category_id, where null means
// Uncategorized. source is not editable here and is never sent.
//
// description has its own rules because the form shows a missing note as
// a blank field, while the API uses null to clear one:
// - untouched field -> omitted;
// - existing note cleared to blank -> null (clears it);
// - still-blank field on an Expense without a note -> omitted;
// - non-blank changed value -> the trimmed string.
function buildExpenseUpdatePayload(
  expense: Expense,
  form: ExpenseFormState,
): ExpenseUpdateInput {
  const changedFields: ExpenseUpdateInput = {};

  if (form.categoryId !== expense.category_id) {
    changedFields.category_id = form.categoryId;
  }

  const normalizedTitle = form.title.trim();

  if (normalizedTitle !== expense.title) {
    changedFields.title = normalizedTitle;
  }

  const normalizedAmount = normalizeExpenseAmount(form.amount);

  if (normalizedAmount !== expense.amount) {
    changedFields.amount = normalizedAmount;
  }

  const normalizedCurrency = form.currency.trim().toUpperCase();

  if (normalizedCurrency !== expense.currency) {
    changedFields.currency = normalizedCurrency;
  }

  const normalizedExpenseDate = form.expenseDate.trim();

  if (normalizedExpenseDate !== expense.expense_date) {
    changedFields.expense_date = normalizedExpenseDate;
  }

  if (form.description !== (expense.description ?? "")) {
    const trimmedDescription = form.description.trim();
    const nextDescription =
      trimmedDescription === "" ? null : trimmedDescription;

    if (nextDescription !== expense.description) {
      changedFields.description = nextDescription;
    }
  }

  if (form.accountId !== expense.account_id) {
    changedFields.account_id = form.accountId;
  }

  return changedFields;
}

export function ExpenseDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { session, isLoading: isAuthLoading } = useAuth();
  const queryClient = useQueryClient();
  const router = useRouter();

  const {
    data: expense,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["expenses", session?.user.id],
    queryFn: getExpenses,
    enabled: Boolean(session),
    select: (expenses) =>
      expenses.find((candidate) => candidate.id === id),
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
  // request path. Used only to show and change the link, never balances.
  const {
    data: accounts = [],
    isLoading: isAccountsLoading,
    error: accountsError,
  } = useQuery({
    queryKey: ["accounts", session?.user.id],
    queryFn: getAccounts,
    enabled: Boolean(session),
  });

  const [title, setTitle] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("EUR");
  const [expenseDate, setExpenseDate] = useState("");
  const [description, setDescription] = useState("");
  const [selectedCategoryId, setSelectedCategoryId] =
    useState<string | null>(null);
  const [selectedAccountId, setSelectedAccountId] =
    useState<string | null>(null);

  // Tracks which expense the form fields were last synced from. `expense`
  // arrives asynchronously (TanStack Query), so it is undefined on first
  // render and only becomes available later -- the fields must be seeded
  // once it does, and re-seeded if the route ever points at a different
  // expense id while this screen instance stays mounted. Adjusting state
  // during render (guarded on identity) is React's recommended replacement
  // for an effect that only exists to sync local state from a prop/query
  // result: https://react.dev/learn/you-might-not-need-an-effect
  const [syncedExpenseId, setSyncedExpenseId] = useState<string | null>(
    null,
  );

  if (expense && expense.id !== syncedExpenseId) {
    setSyncedExpenseId(expense.id);
    setTitle(expense.title);
    setAmount(expense.amount);
    setCurrency(expense.currency);
    setExpenseDate(expense.expense_date);
    setDescription(expense.description ?? "");
    setSelectedCategoryId(expense.category_id);
    setSelectedAccountId(expense.account_id);
  }

  // previousAccountId travels with each mutation's variables (captured at
  // submit time), so invalidation compares the pre-mutation linkage with
  // the backend's result even after the list query has refetched.
  const updateExpenseMutation = useMutation({
    mutationFn: (variables: {
      payload: ExpenseUpdateInput;
      previousAccountId: string | null;
    }) => updateExpense(id, variables.payload),

    onSuccess: async (updatedExpense, variables) => {
      await invalidateExpenseQueries(
        queryClient,
        session?.user.id,
        variables.previousAccountId !== null ||
          updatedExpense.account_id !== null,
      );
      router.back();
    },

    onError: (mutationError) => {
      // Currency mismatch, archived destination, future-dated foreign
      // currency, invalid calendar date, and FX availability are all
      // decided by the backend and surfaced here as its own message.
      Alert.alert(
        "Update expense failed",
        getApiErrorMessage(mutationError, "Unable to update expense."),
      );
    },
  });

  const deleteExpenseMutation = useMutation({
    mutationFn: (variables: { previousAccountId: string | null }) =>
      deleteExpense(id),

    onSuccess: async (_result, variables) => {
      // The backend removes the linked Account debit itself (cascade);
      // the client only refreshes the affected caches.
      await invalidateExpenseQueries(
        queryClient,
        session?.user.id,
        variables.previousAccountId !== null,
      );
      router.back();
    },

    onError: (mutationError) => {
      Alert.alert(
        "Delete expense failed",
        getApiErrorMessage(mutationError, "Unable to delete expense."),
      );
    },
  });

  const isMutating =
    updateExpenseMutation.isPending || deleteExpenseMutation.isPending;

  const changedFields: ExpenseUpdateInput = expense
    ? buildExpenseUpdatePayload(expense, {
        categoryId: selectedCategoryId,
        title,
        amount,
        currency,
        expenseDate,
        description,
        accountId: selectedAccountId,
      })
    : {};

  const hasChanges = Object.keys(changedFields).length > 0;

  function handleSaveExpense() {
    // Guards against duplicate submissions and against sending an empty
    // PATCH, which the backend rejects -- independent of the disabled
    // Save button.
    if (isMutating || !expense || !hasChanges) {
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

    updateExpenseMutation.mutate({
      payload: changedFields,
      previousAccountId: expense.account_id,
    });
  }

  function handleDeleteExpense() {
    if (isMutating || !expense) {
      return;
    }

    const previousAccountId = expense.account_id;

    Alert.alert(
      "Delete expense?",
      previousAccountId !== null
        ? "This also removes its debit from the linked account. This cannot be undone."
        : "This cannot be undone.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: () => deleteExpenseMutation.mutate({ previousAccountId }),
        },
      ],
    );
  }

  if (isAuthLoading || isLoading) {
    return (
      <SafeAreaView>
        <ActivityIndicator />
      </SafeAreaView>
    );
  }

  if (error) {
    return (
      <SafeAreaView>
        <Text>Unable to load expense.</Text>
      </SafeAreaView>
    );
  }

  if (!expense) {
    return (
      <SafeAreaView>
        <Text>Expense not found.</Text>
        <Button title="Back to expenses" onPress={() => router.back()} />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView keyboardShouldPersistTaps="handled">
        <Text>Edit expense</Text>

        <Text>Category</Text>

        {isCategoriesLoading ? (
          <ActivityIndicator />
        ) : categoriesError ? (
          <Text>Unable to load categories.</Text>
        ) : categories.length === 0 ? (
          <Text>No categories available.</Text>
        ) : (
          <View>
            <Button
              title={
                selectedCategoryId === null
                  ? "✓ Uncategorized"
                  : "Uncategorized"
              }
              onPress={() => setSelectedCategoryId(null)}
            />

            {categories.map((category) => (
              <Button
                key={category.id}
                title={
                  selectedCategoryId === category.id
                    ? `✓ ${category.name}`
                    : category.name
                }
                onPress={() => setSelectedCategoryId(category.id)}
              />
            ))}
          </View>
        )}

        <TextInput
          placeholder="Title"
          value={title}
          onChangeText={setTitle}
        />

        <TextInput
          placeholder="Amount"
          value={amount}
          onChangeText={setAmount}
          keyboardType="decimal-pad"
        />

        <Text>Currency</Text>

        <TextInput
          placeholder="EUR"
          value={currency}
          onChangeText={setCurrency}
          autoCapitalize="characters"
          maxLength={3}
        />

        <TextInput
          placeholder="YYYY-MM-DD"
          value={expenseDate}
          onChangeText={setExpenseDate}
        />

        <TextInput
          placeholder="Description (optional)"
          value={description}
          onChangeText={setDescription}
          maxLength={500}
        />

        <Text>Account</Text>

        {/* A failed background refetch keeps the last loaded list, so the
            notice is shown only when no Accounts are available at all.
            While it is shown the selection cannot change, so account_id
            is never part of the PATCH and the current link stays as-is. */}
        {isAccountsLoading ? (
          <ActivityIndicator />
        ) : accountsError && accounts.length === 0 ? (
          <Text>
            Unable to load accounts. The account link will stay unchanged.
          </Text>
        ) : (
          <AccountPicker
            accounts={accounts}
            selectedAccountId={selectedAccountId}
            onChange={setSelectedAccountId}
            currentLinkedAccountId={expense.account_id}
          />
        )}

        <Text>
          Optional — a linked account&apos;s currency must match this
          expense&apos;s currency. Archived accounts can stay linked but
          cannot be chosen as a new account.
        </Text>

        {updateExpenseMutation.isPending ? (
          <ActivityIndicator />
        ) : (
          <Button
            title="Save changes"
            onPress={handleSaveExpense}
            disabled={isMutating || !hasChanges}
          />
        )}

        <View>
          {deleteExpenseMutation.isPending ? (
            <ActivityIndicator />
          ) : (
            <Button
              title="Delete expense"
              color="red"
              onPress={handleDeleteExpense}
              disabled={isMutating}
            />
          )}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
