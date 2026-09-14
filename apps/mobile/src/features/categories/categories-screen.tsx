import { Link } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import {
  ActivityIndicator,
  Pressable,
  SafeAreaView,
  ScrollView,
  Text,
  View,
} from "react-native";

import { useAuth } from "../auth/auth-context";
import { getCategories } from "./category.service";
import { styles } from "./categories.styles";

// Category management list (VF-009B read list + VF-009C create entry point).
// Edit/Delete/Hide-Show are intentionally out of scope for this slice --
// this screen displays the authenticated user's categories, including
// hidden ones, and links to the Create Category form.
export function CategoriesScreen() {
  const { session } = useAuth();

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
              </View>
            ))}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
