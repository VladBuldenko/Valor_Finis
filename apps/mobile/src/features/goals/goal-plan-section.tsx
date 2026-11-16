import { useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";
import { useQuery } from "@tanstack/react-query";

import { QueryBoundary } from "../../components/query-states";
import { useAuth } from "../auth/auth-context";
import {
  normalizeGoalDecimalAmount,
  validateGoalAmountInput,
} from "./goal-amount-validation";
import {
  PLAN_ASSUMPTION,
  PLAN_TITLE,
  PROGRESS_NOTE,
  WHAT_IF_DISCLAIMER,
  WHAT_IF_HINT,
  WHAT_IF_TITLE,
  planProgressRows,
  planRequirement,
  planStatusMessage,
  whatIfMessage,
} from "./goal-plan-view";
import { getGoalPlan } from "./goal.service";
import { styles } from "./goals.styles";

// VF-GOALS-PLANNING-001: the "Goal plan" section of the Goal detail screen.
// Read-only and advisory. Every number and date shown is the backend's answer
// from POST /goals/{id}/plan (goal.service.getGoalPlan); nothing is calculated
// here and nothing is stored, scheduled or reserved.
//
// Cache: both queries live under ["goals", userId, ...], the prefix every Goal
// transaction already invalidates, so a contribution, withdrawal or reservation
// refreshes the plan from the backend. The what-if is a separate query that only
// runs once the user asks for an estimate, so the plan itself never flickers.
// The screen owns the hook (not the section) so its pull-to-refresh can re-read
// the plan together with the rest of the Goal.
export function useGoalPlan(goalId: string) {
  const { session } = useAuth();
  const userId = session?.user.id;
  const [input, setInput] = useState("");
  const [estimate, setEstimate] = useState<string | null>(null);

  const planQuery = useQuery({
    queryKey: ["goals", userId, "plan", goalId, "base"],
    queryFn: ({ signal }) => getGoalPlan(goalId, undefined, signal),
    enabled: Boolean(userId),
  });

  const estimateQuery = useQuery({
    queryKey: ["goals", userId, "plan", goalId, "estimate", estimate],
    queryFn: ({ signal }) => getGoalPlan(goalId, estimate ?? undefined, signal),
    enabled: Boolean(userId) && estimate !== null,
  });

  return { planQuery, estimateQuery, input, setInput, estimate, setEstimate };
}

export type GoalPlanModel = ReturnType<typeof useGoalPlan>;

export function GoalPlanSection({ model }: { model: GoalPlanModel }) {
  const { planQuery, estimateQuery, input, setInput, estimate, setEstimate } = model;

  // Shape only (the same rule as the contribution form); whether an amount
  // makes sense for the Goal is the backend's answer.
  const inputError = validateGoalAmountInput(input, "Monthly amount");
  const canAsk = input !== "" && inputError === null;

  return (
    <View>
      <Text style={styles.sectionTitle} accessibilityRole="header">
        {PLAN_TITLE}
      </Text>

      <QueryBoundary query={planQuery} what="goal plan">
        {(plan) => {
          const requirement = planRequirement(plan);
          const statusMessage = planStatusMessage(plan);

          return (
            <View>
              {planProgressRows(plan).map((row) => (
                <Text
                  key={row.label}
                  style={styles.secondaryText}
                  accessibilityLabel={`${row.label}: ${row.value}`}
                >
                  {row.label}: {row.value}
                </Text>
              ))}

              <Text style={styles.helperText}>{PROGRESS_NOTE}</Text>

              {requirement ? (
                <View style={styles.formGroup} accessible accessibilityLabel={`Needed: ${requirement.headline}. ${requirement.schedule}`}>
                  <Text style={styles.name}>{requirement.headline}</Text>
                  <Text style={styles.secondaryText}>{requirement.schedule}</Text>
                </View>
              ) : null}

              {statusMessage ? <Text style={styles.secondaryText}>{statusMessage}</Text> : null}

              <Text style={styles.helperText}>{PLAN_ASSUMPTION}</Text>

              {plan.plan_status === "archived" ? null : (
                <View style={styles.formGroup}>
                  <Text style={styles.label}>{WHAT_IF_TITLE}</Text>
                  <Text style={styles.helperText}>{WHAT_IF_HINT}</Text>

                  <TextInput
                    style={styles.input}
                    placeholder="0.00"
                    value={input}
                    onChangeText={setInput}
                    keyboardType="decimal-pad"
                    accessibilityLabel="Monthly amount to try"
                  />

                  {inputError ? (
                    <Text style={styles.errorText} accessibilityRole="alert" accessibilityLiveRegion="polite">
                      {inputError}
                    </Text>
                  ) : null}

                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel="Show estimate"
                    accessibilityState={{ disabled: !canAsk }}
                    disabled={!canAsk}
                    style={[styles.button, styles.formGroup]}
                    onPress={() => setEstimate(normalizeGoalDecimalAmount(input))}
                  >
                    <Text style={styles.buttonText}>Show estimate</Text>
                  </Pressable>

                  {estimate !== null ? (
                    <View accessibilityLiveRegion="polite">
                      <QueryBoundary query={estimateQuery} what="estimate">
                        {(result) =>
                          result.what_if ? (
                            <View>
                              <Text style={styles.secondaryText}>{whatIfMessage(result.what_if, result)}</Text>
                              <Text style={styles.helperText}>{WHAT_IF_DISCLAIMER}</Text>
                            </View>
                          ) : null
                        }
                      </QueryBoundary>

                      <Pressable
                        accessibilityRole="button"
                        accessibilityLabel="Clear estimate"
                        style={[styles.editButton, styles.formGroup]}
                        onPress={() => {
                          setEstimate(null);
                          setInput("");
                        }}
                      >
                        <Text style={styles.editButtonText}>Clear</Text>
                      </Pressable>
                    </View>
                  ) : null}
                </View>
              )}
            </View>
          );
        }}
      </QueryBoundary>
    </View>
  );
}
