import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  SafeAreaView,
  ScrollView,
  Text,
  View,
} from "react-native";

import { readApiFailure } from "../../api/api-error-message";
import { useAuth } from "../auth/auth-context";
import {
  canMoveDown,
  canMoveUp,
  canSaveDraft,
  getBaselineGoalIds,
  moveDraftItem,
  resolveDraft,
} from "./goal-priorities";
import { saveGoalPriorities } from "./goal-priorities-save";
import { getGoals, updateGoalPriorities } from "./goal.service";
import { styles } from "./goals.styles";
import type { Goal, GoalStatus } from "./goal.types";

const STATUS_LABELS: Record<GoalStatus, string> = {
  active: "Active",
  completed: "Completed",
  archived: "Archived",
};

/**
 * Dedicated Goal Priorities editor (VF-020D4).
 *
 * Shows the user's non-archived Goals (active and completed) in the
 * backend's canonical order and lets the user reorder them with explicit
 * up / down buttons on a LOCAL draft. Nothing is sent until Save, and a
 * Save is exactly one PUT with the complete ordered id list. The backend
 * response (the complete canonical list, archived Goals included)
 * replaces ["goals", userId] as is.
 */
export function GoalPrioritiesScreen() {
  const { session } = useAuth();
  const queryClient = useQueryClient();
  const userId = session?.user.id;

  const { data: goals = [], isLoading, error } = useQuery({
    queryKey: ["goals", userId],
    queryFn: getGoals,
    enabled: Boolean(session),
  });

  // null = no local edit yet; the editor then shows the authoritative order.
  const [localDraft, setLocalDraft] = useState<string[] | null>(null);

  const baselineIds = getBaselineGoalIds(goals);
  const draftIds = resolveDraft(localDraft, baselineIds);
  const goalsById = new Map<string, Goal>(goals.map((goal) => [goal.id, goal]));

  const saveMutation = useMutation({
    mutationFn: (goalIds: string[]) =>
      saveGoalPriorities(goalIds, {
        updateGoalPriorities,
        replaceGoalsCache: (nextGoals) =>
          queryClient.setQueryData(["goals", userId], nextGoals),
        refetchGoals: () =>
          queryClient.fetchQuery({
            queryKey: ["goals", userId],
            queryFn: getGoals,
            staleTime: 0,
          }),
        readFailureStatus: (failure) => readApiFailure(failure).status,
      }),
    onSuccess: (outcome) => {
      if (outcome.kind === "saved") {
        // The cache now holds the authoritative order, so the baseline moved
        // and the draft is reset to it: Save is disabled again.
        setLocalDraft(null);
        return;
      }

      if (outcome.kind === "stale") {
        // The set changed underneath the user. Never retried or merged: the
        // draft is dropped in favor of the newest server order.
        setLocalDraft(null);
        Alert.alert("Goals updated", outcome.message);
        return;
      }

      // Transient failure: keep the user's draft so they can retry.
      Alert.alert("Save failed", outcome.message);
    },
  });

  function handleMove(index: number, direction: "up" | "down") {
    if (saveMutation.isPending) {
      return;
    }

    setLocalDraft(moveDraftItem(draftIds, index, direction));
  }

  function handleSave() {
    // One PUT per Save: a second tap while the first is in flight is ignored.
    if (!canSaveDraft(draftIds, baselineIds, saveMutation.isPending)) {
      return;
    }

    saveMutation.mutate(draftIds);
  }

  if (isLoading) {
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
          <Text style={styles.errorText}>Unable to load goals.</Text>
        </View>
      </SafeAreaView>
    );
  }

  const isSaveEnabled = canSaveDraft(draftIds, baselineIds, saveMutation.isPending);

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title}>Priorities</Text>

        <Text style={styles.secondaryText}>
          Choose which goals are more important. The goal at the top comes
          first.
        </Text>

        {draftIds.length === 0 ? (
          <Text style={styles.secondaryText}>No goals to prioritize yet.</Text>
        ) : (
          <View style={styles.list}>
            {draftIds.map((goalId, index) => {
              const goal = goalsById.get(goalId);

              if (!goal) {
                return null;
              }

              const upDisabled =
                saveMutation.isPending || !canMoveUp(draftIds, index);
              const downDisabled =
                saveMutation.isPending || !canMoveDown(draftIds, index);

              return (
                <View key={goal.id} style={styles.priorityRow}>
                  <View style={styles.priorityRowText}>
                    <Text style={styles.name}>{goal.name}</Text>

                    <Text style={styles.secondaryText}>
                      {STATUS_LABELS[goal.status]}
                    </Text>
                  </View>

                  <View style={styles.priorityMoveGroup}>
                    <Pressable
                      accessibilityRole="button"
                      accessibilityLabel={`Move ${goal.name} up`}
                      accessibilityState={{ disabled: upDisabled }}
                      disabled={upDisabled}
                      onPress={() => handleMove(index, "up")}
                      style={[
                        styles.priorityMoveButton,
                        upDisabled && styles.priorityMoveButtonDisabled,
                      ]}
                    >
                      <Text style={styles.priorityMoveButtonText}>↑</Text>
                    </Pressable>

                    <Pressable
                      accessibilityRole="button"
                      accessibilityLabel={`Move ${goal.name} down`}
                      accessibilityState={{ disabled: downDisabled }}
                      disabled={downDisabled}
                      onPress={() => handleMove(index, "down")}
                      style={[
                        styles.priorityMoveButton,
                        downDisabled && styles.priorityMoveButtonDisabled,
                      ]}
                    >
                      <Text style={styles.priorityMoveButtonText}>↓</Text>
                    </Pressable>
                  </View>
                </View>
              );
            })}
          </View>
        )}

        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Save goal priorities"
          accessibilityState={{ disabled: !isSaveEnabled }}
          disabled={!isSaveEnabled}
          onPress={handleSave}
          style={[styles.button, styles.formGroup]}
        >
          {saveMutation.isPending ? (
            <ActivityIndicator />
          ) : (
            <Text style={styles.buttonText}>Save order</Text>
          )}
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}
