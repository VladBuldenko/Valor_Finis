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
  SafeAreaView,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";

import { useAuth } from "../auth/auth-context";
import { getCategories } from "../categories/category.service";
import { validateBudgetForm } from "./budget-validation";
import { getBudgets, updateBudget } from "./budget.service";
import { styles } from "./budgets.styles";
import type { BudgetPeriod, BudgetUpdateInput } from "./budget.types";

const BUDGET_PERIODS: BudgetPeriod[] = ["weekly", "monthly", "yearly"];

// Capitalizes a lowercase period literal ("monthly") for display.
// This is presentation-only text formatting, not a financial calculation.
function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export function BudgetEditScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { session, isLoading: isAuthLoading } = useAuth();
  const queryClient = useQueryClient();
  const router = useRouter();

  // There is no GET /budgets/{id} endpoint -- the budget is resolved from
  // the already-fetched ["budgets", userId] list, the same query key and
  // data the Budgets screen and Create Budget's cache invalidation use.
  // This mirrors expense-detail-screen.tsx's resolution pattern exactly.
  const {
    data: budget,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["budgets", session?.user.id],
    queryFn: getBudgets,
    enabled: Boolean(session),
    select: (budgets) =>
      budgets.find((candidate) => candidate.id === id),
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

  const [name, setName] = useState("");
  const [limitAmount, setLimitAmount] = useState("");
  const [period, setPeriod] = useState<BudgetPeriod>("monthly");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [selectedCategoryId, setSelectedCategoryId] =
    useState<string | null>(null);

  const [isCategoryPickerVisible, setIsCategoryPickerVisible] =
    useState(false);
  const [isPeriodPickerVisible, setIsPeriodPickerVisible] = useState(false);

  // Tracks which budget the form fields were last synced from. `budget`
  // arrives asynchronously (TanStack Query), so it is undefined on first
  // render and only becomes available later -- the fields must be seeded
  // once it does. Adjusting state during render (guarded on identity) is
  // React's recommended replacement for an effect that only exists to sync
  // local state from a query result: https://react.dev/learn/you-might-not-need-an-effect
  const [syncedBudgetId, setSyncedBudgetId] = useState<string | null>(null);

  if (budget && budget.id !== syncedBudgetId) {
    setSyncedBudgetId(budget.id);
    setName(budget.name);
    setLimitAmount(budget.limit_amount);
    setPeriod(budget.period);
    setStartDate(budget.start_date);
    setEndDate(budget.end_date ?? "");
    setSelectedCategoryId(budget.category_id);
  }

  const selectedCategoryLabel =
    selectedCategoryId === null
      ? "General budget"
      : (categories.find((category) => category.id === selectedCategoryId)
          ?.name ?? "General budget");

  const updateBudgetMutation = useMutation({
    mutationFn: (payload: BudgetUpdateInput) =>
      updateBudget(id, payload),

    onSuccess: async () => {
      // Same query families Create Budget invalidates -- the budgets list
      // itself and every screen that reads per-budget spending progress
      // (Budgets screen, Dashboard).
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["budgets", session?.user.id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["analytics", "budget-status", session?.user.id],
        }),
      ]);

      router.back();
    },

    onError: (mutationError) => {
      const message =
        mutationError instanceof Error
          ? mutationError.message
          : "Unable to update budget.";

      Alert.alert("Update budget failed", message);
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
          <Text style={styles.errorText}>Unable to load budget.</Text>
        </View>
      </SafeAreaView>
    );
  }

  if (!budget) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.content}>
          <Text style={styles.secondaryText}>Budget not found.</Text>

          <Pressable
            style={styles.button}
            onPress={() => router.back()}
          >
            <Text style={styles.buttonText}>Back to budgets</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  // Builds a PATCH payload containing only the fields the user actually
  // changed, matching the backend's exclude_unset semantics: an omitted
  // field stays unchanged, so unmodified fields must never be sent. Clearing
  // an existing end date sends `end_date: null`; leaving an already-blank
  // end date blank omits it entirely rather than sending a redundant null.
  const normalizedName = name.trim();
  const normalizedLimitAmount = limitAmount.trim().replace(",", ".");
  const trimmedEndDate = endDate.trim();
  const normalizedEndDate = trimmedEndDate || null;

  const changedFields: BudgetUpdateInput = {};

  if (normalizedName !== budget.name) {
    changedFields.name = normalizedName;
  }

  if (normalizedLimitAmount !== budget.limit_amount) {
    changedFields.limit_amount = normalizedLimitAmount;
  }

  if (selectedCategoryId !== budget.category_id) {
    changedFields.category_id = selectedCategoryId;
  }

  if (period !== budget.period) {
    changedFields.period = period;
  }

  if (startDate !== budget.start_date) {
    changedFields.start_date = startDate;
  }

  if (normalizedEndDate !== budget.end_date) {
    changedFields.end_date = normalizedEndDate;
  }

  const hasChanges = Object.keys(changedFields).length > 0;

  function handleSaveChanges() {
    // Guards against duplicate submissions from a double tap while the
    // request is already in flight, and against sending an empty PATCH
    // the backend would reject.
    if (updateBudgetMutation.isPending || !hasChanges) {
      return;
    }

    const validationError = validateBudgetForm({
      name,
      limitAmount,
      startDate,
      endDate,
    });

    if (validationError) {
      Alert.alert("Invalid budget", validationError);
      return;
    }

    updateBudgetMutation.mutate(changedFields);
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
          <Text style={styles.title}>Edit budget</Text>

          <Text style={styles.helperText}>* Required fields</Text>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Name *</Text>

            <TextInput
              style={styles.input}
              placeholder="e.g. Groceries"
              value={name}
              onChangeText={setName}
            />
          </View>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Limit amount *</Text>

            <TextInput
              style={styles.input}
              placeholder="0.00"
              value={limitAmount}
              onChangeText={setLimitAmount}
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
            <Text style={styles.label}>Period</Text>

            <Pressable
              style={styles.selectControl}
              onPress={() => setIsPeriodPickerVisible(true)}
            >
              <Text style={styles.selectControlText}>
                {capitalize(period)}
              </Text>

              <Text style={styles.selectControlChevron}>▾</Text>
            </Pressable>
          </View>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Start date *</Text>

            <TextInput
              style={styles.input}
              placeholder="YYYY-MM-DD"
              value={startDate}
              onChangeText={setStartDate}
            />
          </View>

          <View style={styles.formGroup}>
            <Text style={styles.label}>End date</Text>

            <TextInput
              style={[styles.input, styles.inputOptional]}
              placeholder="YYYY-MM-DD"
              value={endDate}
              onChangeText={setEndDate}
            />

            <Text style={styles.helperText}>
              Optional — leave blank for an ongoing budget.
            </Text>
          </View>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Currency</Text>

            <View style={styles.readOnlyField}>
              <Text style={styles.readOnlyFieldText}>
                {budget.currency}
              </Text>
            </View>
          </View>

          <Pressable
            disabled={updateBudgetMutation.isPending || !hasChanges}
            onPress={handleSaveChanges}
            style={[styles.button, styles.formGroup]}
          >
            {updateBudgetMutation.isPending ? (
              <ActivityIndicator />
            ) : (
              <Text style={styles.buttonText}>Save changes</Text>
            )}
          </Pressable>

          {!hasChanges && !updateBudgetMutation.isPending ? (
            <Text style={styles.helperText}>
              Change a field to enable Save.
            </Text>
          ) : null}
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
                    ? "✓ General budget"
                    : "General budget"}
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

      <Modal
        visible={isPeriodPickerVisible}
        transparent
        animationType="slide"
        onRequestClose={() => setIsPeriodPickerVisible(false)}
      >
        <Pressable
          style={styles.modalOverlay}
          onPress={() => setIsPeriodPickerVisible(false)}
        >
          <Pressable
            style={styles.modalSheet}
            onPress={(event) => event.stopPropagation()}
          >
            <Text style={styles.modalTitle}>Select period</Text>

            <View style={styles.modalOptionList}>
              {BUDGET_PERIODS.map((option) => (
                <Pressable
                  key={option}
                  style={styles.modalOption}
                  onPress={() => {
                    setPeriod(option);
                    setIsPeriodPickerVisible(false);
                  }}
                >
                  <Text
                    style={[
                      styles.modalOptionText,
                      period === option && styles.modalOptionSelectedText,
                    ]}
                  >
                    {period === option
                      ? `✓ ${capitalize(option)}`
                      : capitalize(option)}
                  </Text>
                </Pressable>
              ))}
            </View>

            <Pressable
              style={styles.modalCloseButton}
              onPress={() => setIsPeriodPickerVisible(false)}
            >
              <Text style={styles.buttonText}>Close</Text>
            </Pressable>
          </Pressable>
        </Pressable>
      </Modal>
    </SafeAreaView>
  );
}
