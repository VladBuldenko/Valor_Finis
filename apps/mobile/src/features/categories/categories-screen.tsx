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
import { getCategories, updateCategory } from "./category.service";
import { styles } from "./categories.styles";
import type { Category } from "./category.types";

// Category management list (VF-009B read list, VF-009C create entry point,
// VF-009D edit + hide/show). Delete is intentionally out of scope for this
// slice -- this screen displays the authenticated user's categories,
// including hidden ones, links to the Create Category form, and lets the
// user Edit a custom category or Hide/Show a default one (mutually
// exclusive per the backend's default/custom semantics -- see
// category-edit-screen.tsx's defensive default-category protection).
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

                {/* Custom -> Edit only; Default -> Hide/Show only. The UI
                    itself makes the backend's default/custom semantics
                    obvious rather than relying solely on the backend's 409
                    protection (a default category's name/color/icon are not
                    editable; a custom category's visibility is out of scope
                    for this slice). */}
                {category.is_default === false ? (
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
