import { useState } from "react";
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
import {
  createExpense,
  getExpenses,
} from "./expense.service";

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
  const [expenseDate, setExpenseDate] = useState(
    getCurrentLocalDate,
  );
  const [description, setDescription] = useState("");

  const {
    data: expenses = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["expenses", session?.user.id],
    queryFn: getExpenses,
    enabled: Boolean(session),
  });

  const createExpenseMutation = useMutation({
    mutationFn: createExpense,

    onSuccess: async () => {
      setTitle("");
      setAmount("");
      setDescription("");

      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["expenses", session?.user.id],
        }),
        queryClient.invalidateQueries({
          queryKey: [
            "analytics",
            "monthly-summary",
            session?.user.id,
          ],
        }),
        queryClient.invalidateQueries({
          queryKey: [
            "analytics",
            "category-summary",
            session?.user.id,
          ],
        }),
        queryClient.invalidateQueries({
          queryKey: [
            "analytics",
            "budget-status",
            session?.user.id,
          ],
        }),
      ]);
    },

    onError: (mutationError) => {
      const message =
        mutationError instanceof Error
          ? mutationError.message
          : "Unable to create expense.";

      Alert.alert("Create expense failed", message);
    },
  });

  function handleCreateExpense() {
    const normalizedTitle = title.trim();
    const normalizedAmount = amount.trim().replace(",", ".");
    const normalizedDescription = description.trim();

    if (!normalizedTitle) {
      Alert.alert(
        "Invalid expense",
        "Title is required.",
      );
      return;
    }

    const numericAmount = Number(normalizedAmount);

    if (
      !Number.isFinite(numericAmount) ||
      numericAmount <= 0
    ) {
      Alert.alert(
        "Invalid expense",
        "Amount must be greater than zero.",
      );
      return;
    }

    if (!/^\d{4}-\d{2}-\d{2}$/.test(expenseDate)) {
      Alert.alert(
        "Invalid expense",
        "Date must use YYYY-MM-DD format.",
      );
      return;
    }

    createExpenseMutation.mutate({
      title: normalizedTitle,
      amount: normalizedAmount,
      expense_date: expenseDate,
      description: normalizedDescription || null,
    });
  }

  return (
    <SafeAreaView>
      <ScrollView>
        <Text>Expenses</Text>

        <View>
          <Text>Create expense</Text>

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

          {createExpenseMutation.isPending ? (
            <ActivityIndicator />
          ) : (
            <Button
              title="Add expense"
              onPress={handleCreateExpense}
            />
          )}
        </View>

        {isLoading ? (
          <ActivityIndicator />
        ) : error ? (
          <Text>Unable to load expenses.</Text>
        ) : expenses.length === 0 ? (
          <Text>No expenses yet.</Text>
        ) : (
          <View>
            {expenses.map((expense) => (
              <View key={expense.id}>
                <Text>{expense.title}</Text>

                <Text>
                  {expense.amount} {expense.currency}
                </Text>

                <Text>{expense.expense_date}</Text>
              </View>
            ))}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}