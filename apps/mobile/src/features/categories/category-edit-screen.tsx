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
import { getCategory, updateCategory } from "./category.service";
import { styles } from "./categories.styles";
import type { CategoryUpdateInput } from "./category.types";

// Extracts a user-facing message from a failed category update request.
// Mirrors category-create-screen.tsx's getCategoryCreateErrorMessage
// exactly -- the product wants one consistent duplicate-name message for
// both create and edit, and raw backend JSON is never shown here either.
function getCategoryUpdateErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    const match = error.message.match(/^API request failed: (\d+) .*$/s);

    if (match && match[1] === "409") {
      return "A category with this name already exists.";
    }
  }

  return "Unable to update category.";
}

export function CategoryEditScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { session, isLoading: isAuthLoading } = useAuth();
  const queryClient = useQueryClient();
  const router = useRouter();

  // Unlike Goals/Budgets (no GET-by-id endpoint, resolved from the already-
  // fetched list via `select`), Categories has a verified GET /categories/{id}
  // endpoint, so this screen fetches the single category directly. Cached
  // under its own key, distinct from both existing category query families
  // (["categories", userId, "all"] for the management list, ["categories",
  // userId] for the visible-only Expense/Budget/Receipt pickers) so this
  // fetch never collides with either of their caches.
  const {
    data: category,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["categories", session?.user.id, id],
    queryFn: () => getCategory(id),
    enabled: Boolean(session) && Boolean(id),
  });

  const [name, setName] = useState("");
  const [color, setColor] = useState("");
  const [icon, setIcon] = useState("");

  // Tracks which category the form fields were last synced from. `category`
  // arrives asynchronously (TanStack Query), so it is undefined on first
  // render and only becomes available later -- the fields must be seeded
  // once it does. Adjusting state during render (guarded on identity) is
  // React's recommended replacement for an effect that only exists to sync
  // local state from a query result, and mirrors goal-edit-screen.tsx's /
  // budget-edit-screen.tsx's synced*Id guard. It also protects in-progress
  // edits from a background refetch (e.g. app foreground/refocus): since the
  // guard only re-syncs when the category id itself changes, a refetch that
  // returns the same category never clobbers what the user has typed.
  const [syncedCategoryId, setSyncedCategoryId] = useState<string | null>(
    null,
  );

  if (category && category.id !== syncedCategoryId) {
    setSyncedCategoryId(category.id);
    setName(category.name);
    setColor(category.color ?? "");
    setIcon(category.icon ?? "");
  }

  const updateCategoryMutation = useMutation({
    mutationFn: (payload: CategoryUpdateInput) => updateCategory(id, payload),

    onSuccess: async (_updatedCategory, changedFieldsSent) => {
      // Both category cache variants always need refreshing: the
      // management screen's ["categories", userId, "all"] key, and the
      // visible-only ["categories", userId] key shared by the Expense/
      // Budget/Receipt pickers.
      const invalidations = [
        queryClient.invalidateQueries({
          queryKey: ["categories", session?.user.id, "all"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["categories", session?.user.id],
        }),
      ];

      // category-summary, budget-status, and category-trend (VF-015C) all
      // resolve a category's display name by category_id through the
      // shared build_category_name_map() helper (analytics_service.py) --
      // a rename must be reflected in all three immediately. Spending
      // Trend and the forecast have no category breakdown at all, so a
      // rename never affects them. A color/icon-only edit never changes a
      // displayed name or any historical financial data, so analytics is
      // intentionally left uninvalidated for that case.
      if (changedFieldsSent.name !== undefined) {
        invalidations.push(
          queryClient.invalidateQueries({
            queryKey: ["analytics", "category-summary", session?.user.id],
          }),
          queryClient.invalidateQueries({
            queryKey: ["analytics", "budget-status", session?.user.id],
          }),
          queryClient.invalidateQueries({
            queryKey: ["analytics", "category-trend", session?.user.id],
          }),
        );
      }

      await Promise.all(invalidations);

      router.back();
    },

    onError: (mutationError) => {
      Alert.alert(
        "Update category failed",
        getCategoryUpdateErrorMessage(mutationError),
      );
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
          <Text style={styles.errorText}>Unable to load category.</Text>
        </View>
      </SafeAreaView>
    );
  }

  if (!category) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.content}>
          <Text style={styles.secondaryText}>Category not found.</Text>

          <Pressable style={styles.button} onPress={() => router.back()}>
            <Text style={styles.buttonText}>Back to categories</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  // Defensive protection against manual navigation to a default category's
  // edit URL. The Categories screen never renders an Edit link for a
  // default category (only Hide/Show), but this route is still directly
  // reachable by URL/deep link. The backend would reject a name/color/icon
  // change on a default category with 409 regardless, but this avoids ever
  // showing an editable form for a category the backend does not allow
  // editing that way.
  if (category.is_default) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.content}>
          <Text style={styles.title}>Edit category</Text>

          <Text style={styles.secondaryText}>
            Default categories cannot be edited. Use Hide/Show from
            Categories.
          </Text>

          <Pressable style={styles.button} onPress={() => router.back()}>
            <Text style={styles.buttonText}>Back to categories</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  // Builds a PATCH payload containing only the fields the user actually
  // changed, matching the backend's exclude_unset semantics: an omitted
  // field stays unchanged, so unmodified fields must never be sent. Clearing
  // an existing color/icon sends an explicit null; leaving an already-blank
  // field blank omits it entirely rather than sending a redundant null.
  const normalizedName = name.trim();
  const trimmedColor = color.trim();
  const normalizedColor = trimmedColor || null;
  const trimmedIcon = icon.trim();
  const normalizedIcon = trimmedIcon || null;

  const changedFields: CategoryUpdateInput = {};

  if (normalizedName !== category.name) {
    changedFields.name = normalizedName;
  }

  if (normalizedColor !== category.color) {
    changedFields.color = normalizedColor;
  }

  if (normalizedIcon !== category.icon) {
    changedFields.icon = normalizedIcon;
  }

  const hasChanges = Object.keys(changedFields).length > 0;

  function handleSaveChanges() {
    // Guards against duplicate submissions from a double tap while the
    // request is already in flight.
    if (updateCategoryMutation.isPending) {
      return;
    }

    // Prevents an empty PATCH the backend would reject -- the Save button
    // is already disabled in this state (see below), this is a code-level
    // backstop.
    if (!hasChanges) {
      Alert.alert("No changes to save.");
      return;
    }

    const validationError = validateCategoryForm({ name });

    if (validationError) {
      Alert.alert("Invalid category", validationError);
      return;
    }

    updateCategoryMutation.mutate(changedFields);
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
          <Text style={styles.title}>Edit category</Text>

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
            disabled={updateCategoryMutation.isPending || !hasChanges}
            onPress={handleSaveChanges}
            style={[styles.button, styles.formGroup]}
          >
            {updateCategoryMutation.isPending ? (
              <ActivityIndicator />
            ) : (
              <Text style={styles.buttonText}>Save changes</Text>
            )}
          </Pressable>

          {!hasChanges && !updateCategoryMutation.isPending ? (
            <Text style={styles.helperText}>
              Change a field to enable Save.
            </Text>
          ) : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
