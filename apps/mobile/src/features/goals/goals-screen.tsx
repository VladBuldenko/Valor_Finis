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

export function GoalsScreen() {
  const { session } = useAuth();
  const queryClient = useQueryClient();

  const {
    data: goals = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["goals", session?.user.id],
    queryFn: getGoals,
    enabled: Boolean(session),
  });

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
      const message =
        mutationError instanceof Error
          ? mutationError.message
          : "Unable to delete goal.";

      Alert.alert("Delete goal failed", message);
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
      `"${goal.name}" will be permanently deleted.`,
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

        {goalProgressError ? (
          <Text style={styles.noticeText}>
            Goal progress is temporarily unavailable.
          </Text>
        ) : null}

        {isLoading ? (
          <ActivityIndicator style={styles.loader} />
        ) : error ? (
          <Text style={styles.errorText}>Unable to load goals.</Text>
        ) : goals.length === 0 ? (
          <Text style={styles.secondaryText}>No goals yet.</Text>
        ) : (
          <View style={styles.list}>
            {goals.map((goal) => {
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
