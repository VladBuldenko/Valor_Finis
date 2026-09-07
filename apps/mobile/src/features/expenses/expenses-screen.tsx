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
  Button,
  Pressable,
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
  const [selectedCategoryId, setSelectedCategoryId] =
  useState<string | null>(null);

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

    const validationError = validateExpenseForm({
      title,
      amount,
      expenseDate,
    });

    if (validationError) {
      Alert.alert("Invalid expense", validationError);
      return;
    }

    createExpenseMutation.mutate({
      category_id: selectedCategoryId,
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
                onPress={() =>
                  setSelectedCategoryId(category.id)
                }
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
              <Link
                key={expense.id}
                href={{
                  pathname: "/expenses/[id]",
                  params: { id: expense.id },
                }}
                asChild
              >
                <Pressable>
                  <View>
                    <Text>{expense.title}</Text>

                    <Text>
                      {expense.amount} {expense.currency}
                    </Text>

                    <Text>{expense.expense_date}</Text>
                  </View>
                </Pressable>
              </Link>
            ))}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}