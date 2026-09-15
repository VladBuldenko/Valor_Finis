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
import { validateCategoryForm } from "./category-validation";
import { createCategory } from "./category.service";
import { styles } from "./categories.styles";

// Extracts a user-facing message from a failed category creation request.
// apiRequest (api-client.ts) throws `Error("API request failed: <status>
// <body>")`. Unlike goal-edit-screen's getGoalUpdateErrorMessage (which
// relays the backend's own JSON "detail" text for any status), this screen
// intentionally shows exactly one of two fixed client-side messages: a
// friendly duplicate-name message for 409 (the backend words a plain
// duplicate and a duplicate-of-a-default-name slightly differently, but the
// product wants one consistent message for both), and a generic fallback
// for everything else. Only the numeric status is pulled out of the match --
// the raw backend detail text is never shown here.
function getCategoryCreateErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    const match = error.message.match(/^API request failed: (\d+) .*$/s);

    if (match && match[1] === "409") {
      return "A category with this name already exists.";
    }
  }

  return "Unable to create category.";
}

export function CategoryCreateScreen() {
  const { session } = useAuth();
  const queryClient = useQueryClient();
  const router = useRouter();

  const [name, setName] = useState("");
  const [color, setColor] = useState("");
  const [icon, setIcon] = useState("");

  const createCategoryMutation = useMutation({
    mutationFn: createCategory,

    onSuccess: async () => {
      // Invalidates both category cache variants: the management screen's
      // ["categories", userId, "all"] key (include_hidden=true), and the
      // visible-only ["categories", userId] key shared by the Expense/
      // Budget/Receipt pickers -- both must reflect the new category
      // immediately. Creating an unused category never changes financial
      // analytics, so no analytics query is invalidated here.
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["categories", session?.user.id, "all"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["categories", session?.user.id],
        }),
      ]);

      router.back();
    },

    onError: (mutationError) => {
      Alert.alert(
        "Create category failed",
        getCategoryCreateErrorMessage(mutationError),
      );
    },
  });

  function handleCreateCategory() {
    // Guards against duplicate submissions from a double tap while the
    // request is already in flight.
    if (createCategoryMutation.isPending) {
      return;
    }

    const validationError = validateCategoryForm({ name });

    if (validationError) {
      Alert.alert("Invalid category", validationError);
      return;
    }

    const normalizedName = name.trim();
    const normalizedColor = color.trim();
    const normalizedIcon = icon.trim();

    createCategoryMutation.mutate({
      name: normalizedName,
      color: normalizedColor || null,
      icon: normalizedIcon || null,
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
          <Text style={styles.title}>Create category</Text>

          <Text style={styles.helperText}>* Required fields</Text>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Name *</Text>

            <TextInput
              style={styles.input}
              placeholder="e.g. Pets"
              value={name}
              onChangeText={setName}
              maxLength={80}
            />
          </View>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Color</Text>

            <TextInput
              style={[styles.input, styles.inputOptional]}
              placeholder="e.g. #4A90E2"
              value={color}
              onChangeText={setColor}
            />

            <Text style={styles.helperText}>Optional.</Text>
          </View>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Icon</Text>

            <TextInput
              style={[styles.input, styles.inputOptional]}
              placeholder="e.g. paw"
              value={icon}
              onChangeText={setIcon}
            />

            <Text style={styles.helperText}>Optional.</Text>
          </View>

          <Pressable
            disabled={createCategoryMutation.isPending}
            onPress={handleCreateCategory}
            style={[styles.button, styles.formGroup]}
          >
            {createCategoryMutation.isPending ? (
              <ActivityIndicator />
            ) : (
              <Text style={styles.buttonText}>Save category</Text>
            )}
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
