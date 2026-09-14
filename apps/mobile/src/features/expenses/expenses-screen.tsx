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
  const [expenseDate, setExpenseDate] = useState(
    getCurrentLocalDate,
  );
  const [description, setDescription] = useState("");
  const [selectedCategoryId, setSelectedCategoryId] =
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

  const selectedCategoryLabel =
    selectedCategoryId === null
      ? "Uncategorized"
      : (categories.find((category) => category.id === selectedCategoryId)
          ?.name ?? "Uncategorized");

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
    // Guards against duplicate submissions from a double tap while the
    // request is already in flight.
    if (createExpenseMutation.isPending) {
      return;
    }

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
            />
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
