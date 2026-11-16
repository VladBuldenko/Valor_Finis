import { useState } from "react";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { getApiErrorMessage } from "../../api/api-error-message";
import { LoadError, LoadingState } from "../../components/query-states";
import { useAuth } from "../auth/auth-context";
import { styles } from "../goals/goals.styles";
import { invalidateFutureObligationQueries } from "./future-obligation-cache";
import { FutureObligationForm } from "./future-obligation-form";
import {
  buildUpdatePayload,
  validateFutureObligationForm,
  valuesFromObligation,
  type FutureObligationFormValues,
} from "./future-obligation-validation";
import { archiveConfirmation } from "./future-obligation-view";
import { getFutureObligations, updateFutureObligation } from "./future-obligation.service";
import type { FutureObligationUpdateInput } from "./future-obligation.types";

// VF-GOALS-PLANNING-002C1: "Edit bill". Changes the bill, or archives or restores it.
// An archived bill stays stored but no longer appears in upcoming bills. Nothing
// here pays a bill, sets money aside or adds an expense.
export function FutureObligationEditScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { session, isLoading: isAuthLoading } = useAuth();
  const queryClient = useQueryClient();
  const router = useRouter();

  // The bill is resolved from the list query (the same key the bills screen
  // uses), like the Goal edit screen does for Goals.
  const {
    data: obligation,
    isLoading,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ["future-obligations", session?.user.id, "list"],
    queryFn: ({ signal }) => getFutureObligations(signal),
    enabled: Boolean(session),
    select: (obligations) => obligations.find((candidate) => candidate.id === id),
  });

  const [values, setValues] = useState<FutureObligationFormValues | null>(null);
  const [syncedId, setSyncedId] = useState<string | null>(null);

  // The fields are seeded once the bill arrives (adjusting state during render,
  // guarded on identity, as the Goal edit screen does).
  if (obligation && obligation.id !== syncedId) {
    setSyncedId(obligation.id);
    setValues(valuesFromObligation(obligation));
  }

  const updateMutation = useMutation({
    mutationFn: (payload: FutureObligationUpdateInput) => updateFutureObligation(id, payload),

    onSuccess: async () => {
      await invalidateFutureObligationQueries(queryClient, session?.user.id);
      router.back();
    },

    onError: (mutationError) => {
      Alert.alert("Update failed", getApiErrorMessage(mutationError, "Unable to update the bill."));
    },
  });

  if (isAuthLoading || isLoading) {
    return (
      <SafeAreaView style={styles.container}>
        <LoadingState what="bill" />
      </SafeAreaView>
    );
  }

  if (error && obligation === undefined) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.content}>
          <LoadError what="bill" error={error} retrying={isFetching} onRetry={() => void refetch()} />
        </View>
      </SafeAreaView>
    );
  }

  if (!obligation || values === null) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.content}>
          <Text style={styles.secondaryText}>Bill not found.</Text>

          <Pressable accessibilityRole="button" style={styles.button} onPress={() => router.back()}>
            <Text style={styles.buttonText}>Back to bills</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  // Only what the user changed is sent, so an untouched field is never rewritten.
  const changes = buildUpdatePayload(obligation, values);
  const hasChanges = Object.keys(changes).length > 0;
  const isArchived = obligation.status === "archived";

  function handleSave() {
    if (updateMutation.isPending || !hasChanges || values === null) {
      return;
    }

    const validationError = validateFutureObligationForm(values);

    if (validationError) {
      Alert.alert("Check the bill", validationError);
      return;
    }

    updateMutation.mutate(changes);
  }

  function handleArchiveOrRestore() {
    if (updateMutation.isPending || !obligation) {
      return;
    }

    if (isArchived) {
      updateMutation.mutate({ status: "active" });
      return;
    }

    const { title, message } = archiveConfirmation(obligation.name);

    Alert.alert(title, message, [
      { text: "Cancel", style: "cancel" },
      { text: "Archive", style: "destructive", onPress: () => updateMutation.mutate({ status: "archived" }) },
    ]);
  }

  return (
    <SafeAreaView style={styles.container}>
      <KeyboardAvoidingView style={styles.container} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <Text style={styles.title}>Edit bill</Text>

          <FutureObligationForm
            values={values}
            onChange={setValues}
            schedule={obligation.schedule}
            baseCurrency={null}
          />

          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Save changes"
            accessibilityState={{ disabled: !hasChanges || updateMutation.isPending }}
            disabled={!hasChanges || updateMutation.isPending}
            onPress={handleSave}
            style={[styles.button, styles.formGroup]}
          >
            {updateMutation.isPending ? <ActivityIndicator /> : <Text style={styles.buttonText}>Save changes</Text>}
          </Pressable>

          <Pressable
            accessibilityRole="button"
            accessibilityLabel={isArchived ? "Restore bill" : "Archive bill"}
            disabled={updateMutation.isPending}
            onPress={handleArchiveOrRestore}
            style={[styles.editButton, styles.formGroup]}
          >
            <Text style={styles.editButtonText}>{isArchived ? "Restore bill" : "Archive bill"}</Text>
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
