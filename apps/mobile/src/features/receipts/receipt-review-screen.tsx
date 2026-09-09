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
  SafeAreaView,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";

import { useAuth } from "../auth/auth-context";
import { getCategories } from "../categories/category.service";
import { validateReceiptConfirmForm } from "./receipt-validation";
import {
  confirmReceipt,
  getReceiptById,
} from "./receipt.service";

/**
 * Invalidates every query family a confirmed receipt affects.
 * Matches the invalidation set used after manual expense create/update/
 * delete (see expenses-screen.tsx / expense-detail-screen.tsx), plus the
 * receipts family so a future receipts list stays consistent too.
 */
function invalidateReceiptConfirmationQueries(
  queryClient: ReturnType<typeof useQueryClient>,
  userId: string | undefined,
): Promise<unknown> {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: ["receipts"] }),
    queryClient.invalidateQueries({
      queryKey: ["expenses", userId],
    }),
    queryClient.invalidateQueries({
      queryKey: ["analytics", "monthly-summary", userId],
    }),
    queryClient.invalidateQueries({
      queryKey: ["analytics", "category-summary", userId],
    }),
    queryClient.invalidateQueries({
      queryKey: ["analytics", "budget-status", userId],
    }),
  ]);
}

export function ReceiptReviewScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { session, isLoading: isAuthLoading } = useAuth();
  const queryClient = useQueryClient();
  const router = useRouter();

  const {
    data: receipt,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["receipts", "detail", id],
    queryFn: () => getReceiptById(id),
    enabled: Boolean(session && id),
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

  const [title, setTitle] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("");
  const [expenseDate, setExpenseDate] = useState("");
  const [description, setDescription] = useState("");
  const [selectedCategoryId, setSelectedCategoryId] = useState<
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
  }

  const confirmMutation = useMutation({
    mutationFn: () =>
      confirmReceipt(id, {
        category_id: selectedCategoryId,
        title: title.trim(),
        amount: amount.trim().replace(",", "."),
        currency: currency.trim().toUpperCase(),
        expense_date: expenseDate,
        description: description.trim() || null,
      }),

    onSuccess: async (result) => {
      await invalidateReceiptConfirmationQueries(
        queryClient,
        session?.user.id,
      );

      router.replace({
        pathname: "/expenses/[id]",
        params: { id: result.expense.id },
      });
    },

    onError: (mutationError) => {
      // A confirm can fail because another session already confirmed this
      // receipt first (backend-enforced). Refetch the receipt so the
      // screen switches to the "already confirmed" branch instead of
      // staying on a stale editable form the user could keep resubmitting.
      queryClient.invalidateQueries({
        queryKey: ["receipts", "detail", id],
      });

      const message =
        mutationError instanceof Error
          ? mutationError.message
          : "Unable to confirm receipt.";

      Alert.alert("Confirm failed", message);
    },
  });

  function handleConfirm() {
    if (confirmMutation.isPending) {
      return;
    }

    const validationError = validateReceiptConfirmForm({
      title,
      amount,
      currency,
      expenseDate,
    });

    if (validationError) {
      Alert.alert("Invalid receipt data", validationError);
      return;
    }

    confirmMutation.mutate();
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
        <Text>Unable to load receipt.</Text>
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
    <SafeAreaView>
      <ScrollView>
        <Text>Review receipt</Text>

        <Text>
          Correct anything the scan got wrong before creating the expense.
        </Text>

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
        />

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
