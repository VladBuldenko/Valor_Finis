import { useState } from "react";
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

import { getGoalProgress } from "../analytics/analytics.service";
import type { GoalProgressItem } from "../analytics/analytics.types";
import { useAuth } from "../auth/auth-context";
import { getGoalErrorMessage } from "./goal-error-message";
import { deleteGoal, getGoals } from "./goal.service";
import { styles } from "./goals.styles";
import type { Goal, GoalStatus } from "./goal.types";

// Readable labels for the backend's lowercase status literal. Status is
// rendered as-is from the backend -- this is presentation-only text
// formatting, never a client-side status computation (the backend remains
// the sole authority on whether a goal is active/completed/archived).
const STATUS_LABELS: Record<GoalStatus, string> = {
  active: "Active",
  completed: "Completed",
  archived: "Archived",
};

function formatStatus(status: GoalStatus): string {
  return STATUS_LABELS[status];
}

// Local presentation-only view mode (VF-016F2) -- component state, not a
// backend/domain concept, so it deliberately does not live in
// goal.types.ts alongside the backend-mirroring types. "current"
// intentionally includes both "active" and "completed" goals: only
// "archived" is excluded, since completed remains a valid, visible status.
type GoalListView = "current" | "archived";

function matchesGoalListView(goal: Goal, view: GoalListView): boolean {
  return view === "archived"
    ? goal.status === "archived"
    : goal.status !== "archived";
}

// The empty-state message must reflect the currently filtered view, not
// the full unfiltered goals list -- e.g. a user with only archived goals
// must never see "No goals yet." while viewing Current.
function getGoalsEmptyMessage(
  view: GoalListView,
  totalGoalsCount: number,
): string {
  if (totalGoalsCount === 0) {
    return "No goals yet.";
  }

  return view === "archived" ? "No archived goals." : "No current goals.";
}

export function GoalsScreen() {
  const { session } = useAuth();
  const queryClient = useQueryClient();

  const [listView, setListView] = useState<GoalListView>("current");

  const {
    data: goals = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["goals", session?.user.id],
    queryFn: getGoals,
    enabled: Boolean(session),
  });

  const visibleGoals = goals.filter((goal) =>
    matchesGoalListView(goal, listView),
  );

  const {
    data: goalProgress = [],
    error: goalProgressError,
  } = useQuery({
    queryKey: ["analytics", "goal-progress", session?.user.id],
    queryFn: getGoalProgress,
    enabled: Boolean(session),
  });

  // goal_id on GoalProgressItem is the verified, reliable join key back to
  // a goal's own id -- the analytics service computes exactly one progress
  // item per goal owned by the user (see analytics_service.get_goal_progress),
  // mirroring how BudgetStatusItem.budget_id joins to Budget.id on the
  // Budgets screen.
  const goalProgressById = new Map<string, GoalProgressItem>(
    goalProgress.map((progress) => [progress.goal_id, progress]),
  );

  const deleteGoalMutation = useMutation({
    mutationFn: (goalId: string) => deleteGoal(goalId),

    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["goals", session?.user.id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["analytics", "goal-progress", session?.user.id],
        }),
      ]);
    },

    onError: (mutationError) => {
      // A history-bearing goal cannot be hard-deleted (VF-016E): the
      // backend returns a 409 with a clear detail string ("Goal with
      // transaction history cannot be deleted. Archive it instead."),
      // which getGoalErrorMessage surfaces as-is instead of the raw
      // "API request failed: 409 {...}" wrapper. This screen never
      // auto-archives on a failed delete -- the message tells the user
      // to archive via Edit Goal themselves.
      Alert.alert(
        "Delete goal failed",
        getGoalErrorMessage(mutationError, "Unable to delete goal."),
      );
    },
  });

  function handleDeleteGoal(goal: Goal) {
    // Guards against a double tap firing a second DELETE while the first
    // one is still in flight -- mirrors budgets-screen.tsx's
    // deleteBudgetMutation.isPending guard.
    if (deleteGoalMutation.isPending) {
      return;
    }

    Alert.alert(
      "Delete goal?",
      `"${goal.name}" will be permanently deleted. This is only possible ` +
        "if it has no transaction history yet.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: () => deleteGoalMutation.mutate(goal.id),
        },
      ],
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title}>Goals</Text>

        <Link href="/goals/new" asChild>
          <Pressable style={styles.button}>
            <Text style={styles.buttonText}>Add Goal</Text>
          </Pressable>
        </Link>

        <View style={styles.typeToggleRow}>
          <Pressable
            accessibilityRole="button"
            accessibilityState={{ selected: listView === "current" }}
            style={[
              styles.typeToggleButton,
              listView === "current" && styles.typeToggleButtonSelected,
            ]}
            onPress={() => setListView("current")}
          >
            <Text
              style={[
                styles.typeToggleButtonText,
                listView === "current" && styles.typeToggleButtonTextSelected,
              ]}
            >
              Current
            </Text>
          </Pressable>

          <Pressable
            accessibilityRole="button"
            accessibilityState={{ selected: listView === "archived" }}
            style={[
              styles.typeToggleButton,
              listView === "archived" && styles.typeToggleButtonSelected,
            ]}
            onPress={() => setListView("archived")}
          >
            <Text
              style={[
                styles.typeToggleButtonText,
                listView === "archived" &&
                  styles.typeToggleButtonTextSelected,
              ]}
            >
              Archived
            </Text>
          </Pressable>
        </View>

        {goalProgressError ? (
          <Text style={styles.noticeText}>
            Goal progress is temporarily unavailable.
          </Text>
        ) : null}

        {isLoading ? (
          <ActivityIndicator style={styles.loader} />
        ) : error ? (
          <Text style={styles.errorText}>Unable to load goals.</Text>
        ) : visibleGoals.length === 0 ? (
          <Text style={styles.secondaryText}>
            {getGoalsEmptyMessage(listView, goals.length)}
          </Text>
        ) : (
          <View style={styles.list}>
            {visibleGoals.map((goal) => {
              const progress = goalProgressById.get(goal.id);

              return (
                <View key={goal.id} style={styles.card}>
                  <Text style={styles.name}>{goal.name}</Text>

                  <Text style={styles.secondaryText}>
                    {formatStatus(goal.status)}
                  </Text>

                  <Text style={styles.amount}>
                    {goal.target_amount} {goal.currency}
                  </Text>

                  <Text style={styles.secondaryText}>
                    Saved: {goal.current_amount} {goal.currency}
                  </Text>

                  {progress ? (
                    <>
                      <Text style={styles.secondaryText}>
                        Remaining: {progress.remaining_amount}{" "}
                        {goal.currency}
                      </Text>

                      <Text style={styles.secondaryText}>
                        Progress: {progress.progress_percent}%
                      </Text>
                    </>
                  ) : null}

                  <Text style={styles.secondaryText}>
                    {goal.target_date
                      ? `Target date: ${goal.target_date}`
                      : "No target date"}
                  </Text>

                  <Link
                    href={{
                      pathname: "/goals/[id]",
                      params: { id: goal.id },
                    }}
                    asChild
                  >
                    <Pressable style={styles.editButton}>
                      <Text style={styles.editButtonText}>Manage funds</Text>
                    </Pressable>
                  </Link>

                  <Link
                    href={{
                      pathname: "/goals/[id]/edit",
                      params: { id: goal.id },
                    }}
                    asChild
                  >
                    <Pressable style={styles.editButton}>
                      <Text style={styles.editButtonText}>Edit goal</Text>
                    </Pressable>
                  </Link>

                  <Pressable
                    style={styles.deleteButton}
                    disabled={deleteGoalMutation.isPending}
                    onPress={() => handleDeleteGoal(goal)}
                  >
                    {deleteGoalMutation.isPending &&
                    deleteGoalMutation.variables === goal.id ? (
                      <ActivityIndicator size="small" />
                    ) : (
                      <Text style={styles.deleteButtonText}>
                        Delete goal
                      </Text>
                    )}
                  </Pressable>
                </View>
              );
            })}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
