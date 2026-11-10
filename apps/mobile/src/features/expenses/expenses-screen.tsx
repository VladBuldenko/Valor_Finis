import { useRef, useState } from "react";
import * as Crypto from "expo-crypto";
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
  RefreshControl,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { describeCreateFailure } from "../../api/create-failure";
import { AccountPicker } from "../accounts/account-picker";
import { getAccounts } from "../accounts/account.service";
import { LoadError, LoadingState, QueryBoundary } from "../../components/query-states";
import {
  createSubmitGuard,
  resolveCreateAttempt,
  type CreateAttempt,
} from "../../lib/create-attempts";
import { refetcherOf, useScreenRefresh } from "../../lib/screen-refresh";
import { useAuth } from "../auth/auth-context";
import { getCategories } from "../categories/category.service";
import { invalidateExpenseQueries } from "./expense-cache";
import {
  expensePayloadKey,
  toExpenseCreateInput,
  type ExpenseCreatePayload,
} from "./expense-create-attempt";
import {
  normalizeExpenseAmount,
  validateExpenseForm,
} from "./expense-validation";
import {
  createExpense,
  getExpenses,
} from "./expense.service";
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

  const expensesQuery = useQuery({
    queryKey: ["expenses", session?.user.id],
    queryFn: getExpenses,
    enabled: Boolean(session),
  });

  const categoriesQuery = useQuery({
    queryKey: ["categories", session?.user.id],
    queryFn: getCategories,
    enabled: Boolean(session),
  });
  const categories = categoriesQuery.data ?? [];
  const isCategoriesLoading = categoriesQuery.data === undefined && !categoriesQuery.isError;

  // Same query key/data as the Accounts screen -- no separate Account
  // request path. Used only to offer link destinations, never to compute
  // or display balances.
  const accountsQuery = useQuery({
    queryKey: ["accounts", session?.user.id],
    queryFn: getAccounts,
    enabled: Boolean(session),
  });
  const accounts = accountsQuery.data ?? [];
  const isAccountsLoading = accountsQuery.data === undefined && !accountsQuery.isError;
  // Pull-to-refresh only re-reads the three lists; the form keeps its values.
  const refresh = useScreenRefresh(() => [
    refetcherOf(expensesQuery),
    refetcherOf(categoriesQuery),
    refetcherOf(accountsQuery),
  ]);

  const selectedCategoryLabel =
    selectedCategoryId === null
      ? "Uncategorized"
      : (categories.find((category) => category.id === selectedCategoryId)
          ?.name ?? "Uncategorized");

  // Create idempotency (VF-MVP-CORE-002). The attempts of this form instance
  // are kept across failed submissions, so a retry of the same payload reuses
  // its client_request_id (the backend then replays the saved Expense instead of
  // adding a second one); they are cleared after a success. Refs, not state:
  // they never affect rendering and are only read in event handlers. The guard
  // is synchronous, unlike isPending, which only turns true after a re-render.
  const createAttemptsRef = useRef<CreateAttempt<ExpenseCreatePayload>[]>([]);
  const submitGuardRef = useRef(createSubmitGuard());

  const createExpenseMutation = useMutation({
    mutationFn: createExpense,

    // 201 (new) and 200 (exact replay of an earlier, possibly lost, attempt)
    // are the same success: the body is the Expense's current state either way.
    onSuccess: async (createdExpense) => {
      createAttemptsRef.current = [];

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

    // The attempts are deliberately kept: the request may have been committed
    // even though it failed here, so resubmitting the unchanged form must reuse
    // the same key. Only a key the backend rejected as belonging to a different
    // request is dropped.
    onError: (mutationError) => {
      const failure = describeCreateFailure(
        mutationError,
        "expense",
        "Unable to create expense.",
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

  function handleCreateExpense() {
    // Guards against duplicate submissions from a double tap while the
    // request is already in flight.
    if (createExpenseMutation.isPending || submitGuardRef.current.isBusy()) {
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

    const payload: ExpenseCreatePayload = {
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

    // Entered only after validation, so a rejected form never blocks the next
    // tap; released by onSettled.
    if (!submitGuardRef.current.tryEnter()) {
      return;
    }

    try {
      const { attempt, attempts } = resolveCreateAttempt(
        createAttemptsRef.current,
        session?.user.id ?? "",
        expensePayloadKey(payload),
        payload,
        () => Crypto.randomUUID(),
      );

      createAttemptsRef.current = attempts;
      createExpenseMutation.mutate(toExpenseCreateInput(attempt));
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
          refreshControl={<RefreshControl refreshing={refresh.refreshing} onRefresh={refresh.onRefresh} />}
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
              <LoadingState what="categories" />
            ) : categoriesQuery.isError && categoriesQuery.data === undefined ? (
              <LoadError
                what="categories"
                error={categoriesQuery.error}
                retrying={categoriesQuery.isFetching}
                onRetry={() => void categoriesQuery.refetch()}
              />
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
              <LoadingState what="accounts" />
            ) : accountsQuery.isError && accountsQuery.data === undefined ? (
              <>
                <LoadError
                  what="accounts"
                  error={accountsQuery.error}
                  retrying={accountsQuery.isFetching}
                  onRetry={() => void accountsQuery.refetch()}
                />
                <Text style={styles.helperText}>
                  You can still add this expense without an account.
                </Text>
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

          <QueryBoundary query={expensesQuery} what="expenses" empty="No expenses yet.">
            {(expenses) => (
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
          </QueryBoundary>
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
