import { useState } from "react";
import { useRouter } from "expo-router";
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
import { createBudget } from "./budget.service";
import { styles } from "./budgets.styles";
import type { BudgetPeriod } from "./budget.types";

const BUDGET_PERIODS: BudgetPeriod[] = ["weekly", "monthly", "yearly"];

// Capitalizes a lowercase period literal ("monthly") for display.
// This is presentation-only text formatting, not a financial calculation.
function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function getCurrentLocalDate(): string {
  const now = new Date();

  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");

  return `${year}-${month}-${day}`;
}

export function BudgetCreateScreen() {
  const { session } = useAuth();
  const queryClient = useQueryClient();
  const router = useRouter();

  const [name, setName] = useState("");
  const [limitAmount, setLimitAmount] = useState("");
  const [period, setPeriod] = useState<BudgetPeriod>("monthly");
  const [startDate, setStartDate] = useState(getCurrentLocalDate);
  const [endDate, setEndDate] = useState("");
  const [selectedCategoryId, setSelectedCategoryId] =
    useState<string | null>(null);

  // Compact "tap to open" pickers replace the previous permanently-rendered
  // vertical lists for Category and Period (see VF-007D device-review fix).
  const [isCategoryPickerVisible, setIsCategoryPickerVisible] =
    useState(false);
  const [isPeriodPickerVisible, setIsPeriodPickerVisible] = useState(false);

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
      ? "General budget"
      : (categories.find((category) => category.id === selectedCategoryId)
          ?.name ?? "General budget");

  // The product is currently EUR-first with no multi-currency UX anywhere
  // else in the app (see expense creation, which never sends a currency
  // either). Currency is intentionally not user-editable here; the backend
  // already defaults it to "EUR" when omitted from the request.
  const createBudgetMutation = useMutation({
    mutationFn: createBudget,

    onSuccess: async () => {
      // Budget creation affects the budgets list itself and every screen
      // that reads per-budget spending progress (Budgets screen, Dashboard),
      // but not expense analytics (monthly/category summaries), which are
      // unaffected by creating a budget.
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
          : "Unable to create budget.";

      Alert.alert("Create budget failed", message);
    },
  });

  function handleCreateBudget() {
    // Guards against duplicate submissions from a double tap while the
    // request is already in flight.
    if (createBudgetMutation.isPending) {
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

    const normalizedName = name.trim();
    const normalizedLimitAmount = limitAmount.trim().replace(",", ".");
    const trimmedEndDate = endDate.trim();

    createBudgetMutation.mutate({
      category_id: selectedCategoryId,
      name: normalizedName,
      limit_amount: normalizedLimitAmount,
      period,
      start_date: startDate,
      end_date: trimmedEndDate || null,
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
          <Text style={styles.title}>Create budget</Text>

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
              <Text style={styles.readOnlyFieldText}>EUR</Text>
            </View>
          </View>

          <Pressable
            disabled={createBudgetMutation.isPending}
            onPress={handleCreateBudget}
            style={[styles.button, styles.formGroup]}
          >
            {createBudgetMutation.isPending ? (
              <ActivityIndicator />
            ) : (
              <Text style={styles.buttonText}>Save budget</Text>
            )}
          </Pressable>
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
