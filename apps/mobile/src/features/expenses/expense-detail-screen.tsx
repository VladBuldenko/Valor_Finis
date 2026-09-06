import { useEffect, useState } from "react";
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
import { validateExpenseForm } from "./expense-validation";
import {
  deleteExpense,
  getExpenses,
  updateExpense,
} from "./expense.service";

function invalidateExpenseQueries(
  queryClient: ReturnType<typeof useQueryClient>,
  userId: string | undefined,
): Promise<unknown> {
  return Promise.all([
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

export function ExpenseDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { session } = useAuth();
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

  const [title, setTitle] = useState("");
  const [amount, setAmount] = useState("");
  const [expenseDate, setExpenseDate] = useState("");
  const [description, setDescription] = useState("");
  const [selectedCategoryId, setSelectedCategoryId] =
    useState<string | null>(null);

  useEffect(() => {
    if (!expense) {
      return;
    }

    setTitle(expense.title);
    setAmount(expense.amount);
    setExpenseDate(expense.expense_date);
    setDescription(expense.description ?? "");
    setSelectedCategoryId(expense.category_id);
  }, [expense]);

  const updateExpenseMutation = useMutation({
    mutationFn: () =>
      updateExpense(id, {
        category_id: selectedCategoryId,
        title: title.trim(),
        amount: amount.trim().replace(",", "."),
        expense_date: expenseDate,
        description: description.trim() || null,
      }),

    onSuccess: async () => {
      await invalidateExpenseQueries(queryClient, session?.user.id);
      router.back();
    },

    onError: (mutationError) => {
      const message =
        mutationError instanceof Error
          ? mutationError.message
          : "Unable to update expense.";

      Alert.alert("Update expense failed", message);
    },
  });

  const deleteExpenseMutation = useMutation({
    mutationFn: () => deleteExpense(id),

    onSuccess: async () => {
      await invalidateExpenseQueries(queryClient, session?.user.id);
      router.back();
    },

    onError: (mutationError) => {
      const message =
        mutationError instanceof Error
          ? mutationError.message
          : "Unable to delete expense.";

      Alert.alert("Delete expense failed", message);
    },
  });

  function handleSaveExpense() {
    const validationError = validateExpenseForm({
      title,
      amount,
      expenseDate,
    });

    if (validationError) {
      Alert.alert("Invalid expense", validationError);
      return;
    }

    updateExpenseMutation.mutate();
  }

  function handleDeleteExpense() {
    Alert.alert(
      "Delete expense?",
      "This cannot be undone.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: () => deleteExpenseMutation.mutate(),
        },
      ],
    );
  }

  if (isLoading) {
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
    <SafeAreaView>
      <ScrollView>
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

        {updateExpenseMutation.isPending ? (
          <ActivityIndicator />
        ) : (
          <Button title="Save changes" onPress={handleSaveExpense} />
        )}

        <View>
          {deleteExpenseMutation.isPending ? (
            <ActivityIndicator />
          ) : (
            <Button
              title="Delete expense"
              color="red"
              onPress={handleDeleteExpense}
            />
          )}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
