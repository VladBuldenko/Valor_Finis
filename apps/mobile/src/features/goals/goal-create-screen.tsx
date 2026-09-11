import { useState } from "react";
import { useRouter } from "expo-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  SafeAreaView,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";

import { useAuth } from "../auth/auth-context";
import { validateGoalForm } from "./goal-validation";
import { createGoal } from "./goal.service";
import { styles } from "./goals.styles";

export function GoalCreateScreen() {
  const { session } = useAuth();
  const queryClient = useQueryClient();
  const router = useRouter();

  const [name, setName] = useState("");
  const [targetAmount, setTargetAmount] = useState("");
  const [targetDate, setTargetDate] = useState("");

  // The product is currently EUR-first with no multi-currency UX anywhere
  // else in the app (see Create Budget, which never sends a currency
  // either). Currency is intentionally not user-editable here; the backend
  // already defaults it to "EUR" when omitted from the request.
  const createGoalMutation = useMutation({
    mutationFn: createGoal,

    onSuccess: async () => {
      // Goal creation affects the goals list itself and the goal-progress
      // analytics the Goals screen joins against, but not budget or expense
      // analytics, which are unaffected by creating a goal.
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["goals", session?.user.id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["analytics", "goal-progress", session?.user.id],
        }),
      ]);

      router.back();
    },

    onError: (mutationError) => {
      const message =
        mutationError instanceof Error
          ? mutationError.message
          : "Unable to create goal.";

      Alert.alert("Create goal failed", message);
    },
  });

  function handleCreateGoal() {
    // Guards against duplicate submissions from a double tap while the
    // request is already in flight.
    if (createGoalMutation.isPending) {
      return;
    }

    const validationError = validateGoalForm({
      name,
      targetAmount,
      targetDate,
    });

    if (validationError) {
      Alert.alert("Invalid goal", validationError);
      return;
    }

    const normalizedName = name.trim();
    const normalizedTargetAmount = targetAmount.trim().replace(",", ".");
    const trimmedTargetDate = targetDate.trim();

    createGoalMutation.mutate({
      name: normalizedName,
      target_amount: normalizedTargetAmount,
      target_date: trimmedTargetDate || null,
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
          <Text style={styles.title}>Create goal</Text>

          <Text style={styles.helperText}>* Required fields</Text>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Name *</Text>

            <TextInput
              style={styles.input}
              placeholder="e.g. Emergency fund"
              value={name}
              onChangeText={setName}
            />
          </View>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Target amount *</Text>

            <TextInput
              style={styles.input}
              placeholder="0.00"
              value={targetAmount}
              onChangeText={setTargetAmount}
              keyboardType="decimal-pad"
            />
          </View>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Target date</Text>

            <TextInput
              style={[styles.input, styles.inputOptional]}
              placeholder="YYYY-MM-DD"
              value={targetDate}
              onChangeText={setTargetDate}
            />

            <Text style={styles.helperText}>
              Optional — leave blank for no target date.
            </Text>
          </View>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Currency</Text>

            <View style={styles.readOnlyField}>
              <Text style={styles.readOnlyFieldText}>EUR</Text>
            </View>
          </View>

          <Pressable
            disabled={createGoalMutation.isPending}
            onPress={handleCreateGoal}
            style={[styles.button, styles.formGroup]}
          >
            {createGoalMutation.isPending ? (
              <ActivityIndicator />
            ) : (
              <Text style={styles.buttonText}>Save goal</Text>
            )}
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
