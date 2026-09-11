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
import { validateGoalEditForm } from "./goal-edit-validation";
import { getGoals, updateGoal } from "./goal.service";
import { styles } from "./goals.styles";
import type { GoalStatus, GoalUpdateInput } from "./goal.types";

const GOAL_STATUSES: GoalStatus[] = ["active", "completed", "archived"];

// Readable labels for the backend's lowercase status literal -- presentation
// -only text formatting, matching goals-screen.tsx's STATUS_LABELS. Status
// remains fully backend-authoritative: this screen never derives or changes
// it automatically (e.g. reaching 100% saved does not auto-select Completed).
const STATUS_LABELS: Record<GoalStatus, string> = {
  active: "Active",
  completed: "Completed",
  archived: "Archived",
};

// Extracts a user-facing message from a failed goal update request.
// apiRequest (api-client.ts) throws `Error("API request failed: <status>
// <body>")`, where <body> is the raw response text -- for domain errors
// (e.g. the 400 GoalInvalidAmountError, or a 404) that body is FastAPI JSON
// with a string "detail" field. When it parses that way, the backend's own
// detail text is shown instead of the raw "API request failed: ..."
// wrapper, so the amount-invariant error reads as a normal message rather
// than a technical one. Falls back to the raw error message otherwise (e.g.
// a network failure has no such body, and a 422's detail is a structured
// list rather than a string) -- this intentionally never invents new error
// copy that could drift from what the backend actually says.
function getGoalUpdateErrorMessage(error: unknown): string {
  if (!(error instanceof Error)) {
    return "Unable to update goal.";
  }

  const match = error.message.match(/^API request failed: \d+ (.*)$/s);

  if (match) {
    try {
      const body = JSON.parse(match[1]) as { detail?: unknown };

      if (typeof body.detail === "string") {
        return body.detail;
      }
    } catch {
      // Response body wasn't JSON -- fall through to the raw message below.
    }
  }

  return error.message;
}

export function GoalEditScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { session, isLoading: isAuthLoading } = useAuth();
  const queryClient = useQueryClient();
  const router = useRouter();

  // There is no GET /goals/{id} endpoint -- the goal is resolved from the
  // already-fetched ["goals", userId] list, the same query key and data the
  // Goals screen and Create Goal's cache invalidation use. Mirrors
  // budget-edit-screen.tsx's resolution pattern exactly.
  const {
    data: goal,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["goals", session?.user.id],
    queryFn: getGoals,
    enabled: Boolean(session),
    select: (goals) => goals.find((candidate) => candidate.id === id),
  });

  const [name, setName] = useState("");
  const [targetAmount, setTargetAmount] = useState("");
  const [currentAmount, setCurrentAmount] = useState("");
  const [targetDate, setTargetDate] = useState("");
  const [status, setStatus] = useState<GoalStatus>("active");

  const [isStatusPickerVisible, setIsStatusPickerVisible] = useState(false);

  // Tracks which goal the form fields were last synced from. `goal` arrives
  // asynchronously (TanStack Query), so it is undefined on first render and
  // only becomes available later -- the fields must be seeded once it does.
  // Adjusting state during render (guarded on identity) is React's
  // recommended replacement for an effect that only exists to sync local
  // state from a query result, and mirrors budget-edit-screen.tsx's
  // syncedBudgetId guard.
  const [syncedGoalId, setSyncedGoalId] = useState<string | null>(null);

  if (goal && goal.id !== syncedGoalId) {
    setSyncedGoalId(goal.id);
    setName(goal.name);
    setTargetAmount(goal.target_amount);
    setCurrentAmount(goal.current_amount);
    setTargetDate(goal.target_date ?? "");
    setStatus(goal.status);
  }

  const updateGoalMutation = useMutation({
    mutationFn: (payload: GoalUpdateInput) => updateGoal(id, payload),

    onSuccess: async () => {
      // Same query families Create Goal invalidates -- the goals list
      // itself and the goal-progress analytics the Goals screen joins
      // against. Updated amounts/progress come from the refetch, never
      // from a locally fabricated value.
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
      Alert.alert("Update goal failed", getGoalUpdateErrorMessage(mutationError));
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
          <Text style={styles.errorText}>Unable to load goal.</Text>
        </View>
      </SafeAreaView>
    );
  }

  if (!goal) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.content}>
          <Text style={styles.secondaryText}>Goal not found.</Text>

          <Pressable style={styles.button} onPress={() => router.back()}>
            <Text style={styles.buttonText}>Back to goals</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  // Builds a PATCH payload containing only the fields the user actually
  // changed, matching the backend's exclude_unset semantics: an omitted
  // field stays unchanged, so unmodified fields must never be sent.
  // Clearing an existing target date sends `target_date: null`; leaving an
  // already-blank target date blank omits it entirely rather than sending a
  // redundant null. currency is never included -- it is read-only in this
  // UI and always shown as the goal's actual value, never hardcoded.
  const normalizedName = name.trim();
  const normalizedTargetAmount = targetAmount.trim().replace(",", ".");
  const normalizedCurrentAmount = currentAmount.trim().replace(",", ".");
  const trimmedTargetDate = targetDate.trim();
  const normalizedTargetDate = trimmedTargetDate || null;

  const changedFields: GoalUpdateInput = {};

  if (normalizedName !== goal.name) {
    changedFields.name = normalizedName;
  }

  if (normalizedTargetAmount !== goal.target_amount) {
    changedFields.target_amount = normalizedTargetAmount;
  }

  if (normalizedCurrentAmount !== goal.current_amount) {
    changedFields.current_amount = normalizedCurrentAmount;
  }

  if (normalizedTargetDate !== goal.target_date) {
    changedFields.target_date = normalizedTargetDate;
  }

  if (status !== goal.status) {
    changedFields.status = status;
  }

  const hasChanges = Object.keys(changedFields).length > 0;

  function handleSaveChanges() {
    // Guards against duplicate submissions from a double tap while the
    // request is already in flight, and against sending an empty PATCH the
    // backend would reject.
    if (updateGoalMutation.isPending || !hasChanges) {
      return;
    }

    const validationError = validateGoalEditForm({
      name,
      targetAmount,
      currentAmount,
      targetDate,
      status,
    });

    if (validationError) {
      Alert.alert("Invalid goal", validationError);
      return;
    }

    updateGoalMutation.mutate(changedFields);
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
          <Text style={styles.title}>Edit goal</Text>

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
            <Text style={styles.label}>Saved so far *</Text>

            <TextInput
              style={styles.input}
              placeholder="0.00"
              value={currentAmount}
              onChangeText={setCurrentAmount}
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
            <Text style={styles.label}>Status</Text>

            <Pressable
              style={styles.selectControl}
              onPress={() => setIsStatusPickerVisible(true)}
            >
              <Text style={styles.selectControlText}>
                {STATUS_LABELS[status]}
              </Text>

              <Text style={styles.selectControlChevron}>▾</Text>
            </Pressable>
          </View>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Currency</Text>

            <View style={styles.readOnlyField}>
              <Text style={styles.readOnlyFieldText}>{goal.currency}</Text>
            </View>
          </View>

          <Pressable
            disabled={updateGoalMutation.isPending || !hasChanges}
            onPress={handleSaveChanges}
            style={[styles.button, styles.formGroup]}
          >
            {updateGoalMutation.isPending ? (
              <ActivityIndicator />
            ) : (
              <Text style={styles.buttonText}>Save changes</Text>
            )}
          </Pressable>

          {!hasChanges && !updateGoalMutation.isPending ? (
            <Text style={styles.helperText}>
              Change a field to enable Save.
            </Text>
          ) : null}
        </ScrollView>
      </KeyboardAvoidingView>

      <Modal
        visible={isStatusPickerVisible}
        transparent
        animationType="slide"
        onRequestClose={() => setIsStatusPickerVisible(false)}
      >
        <Pressable
          style={styles.modalOverlay}
          onPress={() => setIsStatusPickerVisible(false)}
        >
          <Pressable
            style={styles.modalSheet}
            onPress={(event) => event.stopPropagation()}
          >
            <Text style={styles.modalTitle}>Select status</Text>

            <View style={styles.modalOptionList}>
              {GOAL_STATUSES.map((option) => (
                <Pressable
                  key={option}
                  style={styles.modalOption}
                  onPress={() => {
                    setStatus(option);
                    setIsStatusPickerVisible(false);
                  }}
                >
                  <Text
                    style={[
                      styles.modalOptionText,
                      status === option && styles.modalOptionSelectedText,
                    ]}
                  >
                    {status === option
                      ? `✓ ${STATUS_LABELS[option]}`
                      : STATUS_LABELS[option]}
                  </Text>
                </Pressable>
              ))}
            </View>

            <Pressable
              style={styles.modalCloseButton}
              onPress={() => setIsStatusPickerVisible(false)}
            >
              <Text style={styles.buttonText}>Close</Text>
            </Pressable>
          </Pressable>
        </Pressable>
      </Modal>
    </SafeAreaView>
  );
}
