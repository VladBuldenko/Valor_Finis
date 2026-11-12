import { useRef, useState } from "react";
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
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { getApiErrorMessage } from "../../api/api-error-message";
import { AccountPicker } from "../accounts/account-picker";
import { getAccounts } from "../accounts/account.service";
import { LoadError, LoadingState, RetryAction } from "../../components/query-states";
import { useAuth } from "../auth/auth-context";
import { getCategories } from "../categories/category.service";
import { isCurrentQueryClient } from "../../lib/session-runtime";
import { normalizeExpenseAmount } from "../expenses/expense-validation";
import {
  invalidateConfirmedReceiptQueries,
  recoverFailedConfirmation,
} from "./receipt-confirm-recovery";
import { validateReceiptConfirmForm } from "./receipt-validation";
import {
  confirmReceipt,
  getReceiptById,
} from "./receipt.service";
import type { ReceiptConfirmInput } from "./receipt.types";

const styles = StyleSheet.create({
  // Lets the review form's ScrollView take the remaining height so the
  // longer form (with the Account field) stays scrollable.
  container: {
    flex: 1,
  },
});

export function ReceiptReviewScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { session, isLoading: isAuthLoading } = useAuth();
  const queryClient = useQueryClient();
  const router = useRouter();

  const {
    data: receipt,
    isLoading,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ["receipts", "detail", id],
    queryFn: () => getReceiptById(id),
    enabled: Boolean(session && id),
  });

  const {
    data: categories = [],
    isLoading: isCategoriesLoading,
    error: categoriesError,
    refetch: refetchCategories,
    isFetching: isCategoriesFetching,
  } = useQuery({
    queryKey: ["categories", session?.user.id],
    queryFn: getCategories,
    enabled: Boolean(session),
  });

  // Same query key/data as the Accounts screen -- no separate Account
  // request path. Used only to offer link destinations, never balances.
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

  const [title, setTitle] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("");
  const [expenseDate, setExpenseDate] = useState("");
  const [description, setDescription] = useState("");
  const [selectedCategoryId, setSelectedCategoryId] = useState<
    string | null
  >(null);
  const [selectedAccountId, setSelectedAccountId] = useState<
    string | null
  >(null);

  // Prefills the editable fields from OCR-detected data exactly once per
  // receipt. Undetected fields are left blank rather than fabricated, so
  // the user must fill them in manually. Adjusting state during render
  // (guarded on identity) mirrors expense-detail-screen.tsx's approach to
  // seeding local form state from an asynchronously loaded query result.
  const [syncedReceiptId, setSyncedReceiptId] = useState<string | null>(
    null,
  );

  if (receipt && receipt.id !== syncedReceiptId) {
    setSyncedReceiptId(receipt.id);
    setTitle(receipt.merchant_detected ?? "");
    setAmount(receipt.total_amount_detected ?? "");
    setCurrency(receipt.currency_detected ?? "");
    setExpenseDate(receipt.purchase_date_detected ?? "");
    setDescription("");
    setSelectedCategoryId(null);
    setSelectedAccountId(null);
  }

  // Closes the gap between a tap and the mutation's pending state reaching a
  // render: a second tap in that window would otherwise send a second POST.
  const confirmInFlight = useRef(false);

  const confirmMutation = useMutation({
    mutationFn: (payload: ReceiptConfirmInput) => confirmReceipt(id, payload),

    onSuccess: async (result) => {
      // The confirmed receipt created an Expense, so the Expense/analytics
      // set (plus the Account caches when the backend linked it -- decided
      // from the returned expense, not the form) is refreshed through the
      // shared helper; ["receipts"] also covers ["receipts","detail",id].
      await invalidateConfirmedReceiptQueries(
        queryClient,
        session?.user.id,
        result.expense.account_id !== null,
      );

      // The user may have changed while the caches were refreshing.
      if (!isCurrentQueryClient(queryClient)) {
        return;
      }

      router.replace({
        pathname: "/expenses/[id]",
        params: { id: result.expense.id },
      });
    },

    onError: async (mutationError) => {
      // The confirmation is never resent. A failed request does not prove
      // that nothing happened (a lost response, or another device confirmed
      // first), so the receipt is reread: when it reads "confirmed" the
      // Expense exists, the Expense/Account/analytics caches are refreshed
      // and the screen switches to its "already confirmed" branch. When it
      // is still processed (e.g. an Account currency mismatch) the form and
      // its values stay for another attempt.
      const recovery = await recoverFailedConfirmation(
        queryClient,
        session?.user.id,
        id,
        getReceiptById,
      );

      if (!isCurrentQueryClient(queryClient)) {
        return;
      }

      if (recovery.confirmed) {
        Alert.alert(
          "Receipt already confirmed",
          "This receipt was confirmed and its expense has been created.",
        );

        return;
      }

      Alert.alert(
        "Confirm failed",
        getApiErrorMessage(mutationError, "Unable to confirm receipt."),
      );
    },

    onSettled: () => {
      confirmInFlight.current = false;
    },
  });

  function handleConfirm() {
    if (confirmMutation.isPending || confirmInFlight.current) {
      return;
    }

    const validationError = validateReceiptConfirmForm({
      title,
      amount,
      currency,
      expenseDate,
      description,
    });

    if (validationError) {
      Alert.alert("Invalid receipt data", validationError);
      return;
    }

    // One-shot create: the final form values are sent as-is (the backend
    // falls back to OCR-detected data only for omitted fields).
    const payload: ReceiptConfirmInput = {
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

    confirmInFlight.current = true;
    confirmMutation.mutate(payload);
  }

  if (isAuthLoading || isLoading) {
    return (
      <SafeAreaView>
        <LoadingState what="receipt" />
      </SafeAreaView>
    );
  }

  if (error && receipt === undefined) {
    return (
      <SafeAreaView>
        <LoadError what="receipt" error={error} retrying={isFetching} onRetry={() => void refetch()} />
        <Button title="Back" onPress={() => router.back()} />
      </SafeAreaView>
    );
  }

  if (!receipt) {
    return (
      <SafeAreaView>
        <Text>Receipt not found.</Text>
        <Button title="Back" onPress={() => router.back()} />
      </SafeAreaView>
    );
  }

  if (receipt.status === "confirmed") {
    const confirmedExpenseId = receipt.expense_id;

    return (
      <SafeAreaView>
        <Text>This receipt has already been confirmed.</Text>

        {confirmedExpenseId ? (
          <Button
            title="View expense"
            onPress={() =>
              router.replace({
                pathname: "/expenses/[id]",
                params: { id: confirmedExpenseId },
              })
            }
          />
        ) : (
          <Button
            title="Back to expenses"
            onPress={() => router.replace("/expenses")}
          />
        )}
      </SafeAreaView>
    );
  }

  if (receipt.status !== "processed") {
    return (
      <SafeAreaView>
        <Text>This receipt is not ready for review yet.</Text>
        <Button title="Back" onPress={() => router.back()} />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView keyboardShouldPersistTaps="handled">
        <Text>Review receipt</Text>

        <Text>
          Correct anything the scan got wrong before creating the expense.
        </Text>

        <Text>Category</Text>

        {isCategoriesLoading ? (
          <LoadingState what="categories" />
        ) : categoriesError && categories.length === 0 ? (
          <LoadError what="categories" error={categoriesError} retrying={isCategoriesFetching} onRetry={() => void refetchCategories()} />
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

        <TextInput
          placeholder="Currency (e.g. EUR)"
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
            notice is shown only when no Accounts are available at all --
            in that state nothing was ever selectable, so the receipt is
            confirmed unlinked and no selection is ever sent invisibly. */}
        {isAccountsLoading ? (
          <LoadingState what="accounts" />
        ) : accountsError && accounts.length === 0 ? (
          <>
            <Text>
            Unable to load accounts. You can still confirm this receipt
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

        <Text>
          Optional — a linked account&apos;s currency must match this
          expense&apos;s currency.
        </Text>

        {confirmMutation.isPending ? (
          <ActivityIndicator />
        ) : (
          <Button
            title="Confirm"
            onPress={handleConfirm}
            disabled={confirmMutation.isPending}
          />
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
