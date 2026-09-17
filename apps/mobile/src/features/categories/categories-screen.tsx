import { Link } from "expo-router";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  SafeAreaView,
  ScrollView,
  Text,
  View,
} from "react-native";

import { useAuth } from "../auth/auth-context";
import {
  deleteCategory,
  getCategories,
  updateCategory,
} from "./category.service";
import { styles } from "./categories.styles";
import type { Category } from "./category.types";

// Extracts a user-facing message from a failed category delete request.
// Mirrors category-create-screen.tsx's getCategoryCreateErrorMessage /
// category-edit-screen.tsx's getCategoryUpdateErrorMessage in shape, but
// kept as its own small helper (not shared) since each screen's mapping is
// tied to its own endpoint's failure modes -- delete's defensive case is
// the backend's default-category conflict, not create/edit's duplicate name.
// The UI already never renders Delete for a default category (see below),
// so this is a defensive fallback only, e.g. for a stale render or a race
// with another client toggling/editing the same category concurrently.
function getCategoryDeleteErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    const match = error.message.match(/^API request failed: (\d+) .*$/s);

    if (match && match[1] === "409") {
      return "Default categories cannot be deleted.";
    }
  }

  return "Unable to delete category.";
}

// Category management list (VF-009B read list, VF-009C create entry point,
// VF-009D edit + hide/show, VF-009E delete). This screen displays the
// authenticated user's categories, including hidden ones, links to the
// Create Category form, and lets the user manage a custom category (Edit +
// Delete) or a default one (Hide/Show only) -- mutually exclusive per the
// backend's default/custom semantics (see category-edit-screen.tsx's
// defensive default-category protection and deleteCategory's docstring).
export function CategoriesScreen() {
  const { session } = useAuth();
  const queryClient = useQueryClient();

  // Unlike the visible-only ["categories", userId] key shared by the
  // Expense/Budget/Receipt pickers, this management screen requests
  // `include_hidden=true` and stores it under a distinct ["categories",
  // userId, "all"] key so this fetch never overwrites the pickers' cache
  // with hidden categories they don't expect.
  const {
    data: categories = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["categories", session?.user.id, "all"],
    queryFn: () => getCategories({ includeHidden: true }),
    enabled: Boolean(session),
  });

  const toggleVisibilityMutation = useMutation({
    mutationFn: ({
      categoryId,
      isVisible,
    }: {
      categoryId: string;
      isVisible: boolean;
    }) => updateCategory(categoryId, { is_visible: isVisible }),

    onSuccess: async () => {
      // Only the two category cache variants need refreshing: the
      // management screen's ["categories", userId, "all"] key (so Status
      // flips immediately) and the visible-only ["categories", userId] key
      // shared by the Expense/Budget/Receipt pickers (so a hidden default
      // immediately disappears from -- or a shown one reappears in --
      // normal category selection). Visibility never changes historical
      // financial data, so no analytics query is invalidated here.
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["categories", session?.user.id, "all"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["categories", session?.user.id],
        }),
      ]);
    },

    onError: (mutationError) => {
      const message =
        mutationError instanceof Error
          ? mutationError.message
          : "Unable to update category visibility.";

      Alert.alert("Update category failed", message);
    },
  });

  function handleToggleVisibility(category: Category) {
    // Guards against a double tap firing a second PATCH for the same
    // category while the first one is still in flight.
    if (toggleVisibilityMutation.isPending) {
      return;
    }

    toggleVisibilityMutation.mutate({
      categoryId: category.id,
      isVisible: !category.is_visible,
    });
  }

  const deleteCategoryMutation = useMutation({
    mutationFn: (categoryId: string) => deleteCategory(categoryId),

    onSuccess: async () => {
      // Deleting a custom category has real FK-side effects (backend
      // ON DELETE SET NULL on Expense.category_id / Budget.category_id), so
      // beyond the two category caches, every cache that could hold the
      // deleted category_id or a category-derived label must also refresh:
      // - ["categories", userId, "all"] / ["categories", userId]: the
      //   deleted category must disappear from management and from every
      //   Expense/Budget/Receipt category picker.
      // - ["expenses", userId]: cached expenses may carry the now-stale
      //   category_id (Expense detail resolves via `select` from this same
      //   list query -- no separate detail key exists to invalidate).
      // - ["budgets", userId]: same reasoning for Budget.category_id
      //   (Budget edit also resolves via `select` from this same list
      //   query).
      // - ["analytics", "category-summary", userId]: affected expense
      //   amounts move to Uncategorized.
      // - ["analytics", "budget-status", userId]: budget/category
      //   association and label may change.
      // - ["analytics", "category-trend", userId] (VF-015C): same
      //   Uncategorized regrouping as category-summary above.
      // Deliberately NOT invalidated: "monthly-summary" and
      // "spending-trend"/"spending-forecast" (VF-015B/D) - expense amounts
      // and totals are unchanged by a category deletion, only the category
      // grouping is - and "goals"/"goal-progress" (Goal has no category_id
      // at all).
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["categories", session?.user.id, "all"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["categories", session?.user.id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["expenses", session?.user.id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["budgets", session?.user.id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["analytics", "category-summary", session?.user.id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["analytics", "budget-status", session?.user.id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["analytics", "category-trend", session?.user.id],
        }),
      ]);
    },

    onError: (mutationError) => {
      Alert.alert(
        "Delete category failed",
        getCategoryDeleteErrorMessage(mutationError),
      );
    },
  });

  function handleDeleteCategory(category: Category) {
    // Guards against a double tap firing a second DELETE for the same
    // category while the first one is still in flight -- mirrors
    // budgets-screen.tsx's / goals-screen.tsx's delete-mutation guard.
    if (deleteCategoryMutation.isPending) {
      return;
    }

    Alert.alert(
      "Delete category?",
      `Delete "${category.name}"? Existing expenses and budgets will not ` +
        "be deleted, but they will become uncategorized.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: () => deleteCategoryMutation.mutate(category.id),
        },
      ],
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title}>Categories</Text>

        <Link href="/categories/new" asChild>
          <Pressable style={styles.button}>
            <Text style={styles.buttonText}>Add Category</Text>
          </Pressable>
        </Link>

        {isLoading ? (
          <ActivityIndicator style={styles.loader} />
        ) : error ? (
          <Text style={styles.errorText}>Unable to load categories.</Text>
        ) : categories.length === 0 ? (
          <Text style={styles.secondaryText}>No categories yet.</Text>
        ) : (
          <View style={styles.list}>
            {categories.map((category) => (
              <View key={category.id} style={styles.card}>
                <Text style={styles.name}>{category.name}</Text>

                <Text style={styles.secondaryText}>
                  Type: {category.is_default ? "Default" : "Custom"}
                </Text>

                <Text
                  style={
                    category.is_visible
                      ? styles.secondaryText
                      : styles.hiddenStatusText
                  }
                >
                  Status: {category.is_visible ? "Visible" : "Hidden"}
                </Text>

                {category.color ? (
                  <Text style={styles.secondaryText}>
                    Color: {category.color}
                  </Text>
                ) : null}

                {category.icon ? (
                  <Text style={styles.secondaryText}>
                    Icon: {category.icon}
                  </Text>
                ) : null}

                {/* Custom -> Edit + Delete; Default -> Hide/Show only. The
                    UI itself makes the backend's default/custom semantics
                    obvious rather than relying solely on the backend's 409
                    protection (a default category's name/color/icon are not
                    editable and it cannot be deleted; a custom category's
                    visibility is out of scope for this slice). */}
                {category.is_default === false ? (
                  <>
                    <Link
                      href={{
                        pathname: "/categories/[id]/edit",
                        params: { id: category.id },
                      }}
                      asChild
                    >
                      <Pressable style={styles.editButton}>
                        <Text style={styles.editButtonText}>Edit</Text>
                      </Pressable>
                    </Link>

                    <Pressable
                      style={styles.deleteButton}
                      disabled={deleteCategoryMutation.isPending}
                      onPress={() => handleDeleteCategory(category)}
                    >
                      {deleteCategoryMutation.isPending &&
                      deleteCategoryMutation.variables === category.id ? (
                        <ActivityIndicator size="small" />
                      ) : (
                        <Text style={styles.deleteButtonText}>Delete</Text>
                      )}
                    </Pressable>
                  </>
                ) : (
                  <Pressable
                    style={styles.editButton}
                    disabled={toggleVisibilityMutation.isPending}
                    onPress={() => handleToggleVisibility(category)}
                  >
                    {toggleVisibilityMutation.isPending &&
                    toggleVisibilityMutation.variables?.categoryId ===
                      category.id ? (
                      <ActivityIndicator size="small" />
                    ) : (
                      <Text style={styles.editButtonText}>
                        {category.is_visible ? "Hide" : "Show"}
                      </Text>
                    )}
                  </Pressable>
                )}
              </View>
            ))}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
