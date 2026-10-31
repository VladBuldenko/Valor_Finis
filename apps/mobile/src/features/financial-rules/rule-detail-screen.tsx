import { useRef, useState } from "react";
import { Link, useLocalSearchParams, useRouter } from "expo-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  RefreshControl,
  SafeAreaView,
  ScrollView,
  Text,
  View,
} from "react-native";

import { getAccounts } from "../accounts/account.service";
import { useAuth } from "../auth/auth-context";
import { getBudgets } from "../budgets/budget.service";
import { getGoals } from "../goals/goal.service";
import {
  applyRuleChangeInvalidation,
  createRuleActionRunner,
  createSubmitGuard,
  getRuleActionAvailability,
} from "./financial-rule-actions";
import { COPY, SOURCE_COPY } from "./financial-rule-copy";
import { describeRuleError } from "./financial-rule-errors";
import { financialRuleKeys } from "./financial-rule-query-keys";
import {
  executionModeInfo,
  rulePolicyLabel,
  ruleActionLabel,
  ruleStatusInfo,
  ruleTypeLabel,
} from "./financial-rule-presentation";
import { financialRulesService } from "./financial-rule.service";
import type { FinancialRule, RuleAction } from "./financial-rule.types";
import { styles } from "./rules.styles";

const SIGNED_OUT_KEY = ["financial-rules", "signed-out"] as const;
const runner = createRuleActionRunner(financialRulesService);

const CONFIRM_TEXT: Record<"pause" | "disable" | "delete", { title: string; message: string; button: string }> = {
  pause: {
    title: "Pause this rule?",
    message: "It will stop running, and any suggestions still waiting for you will be cancelled.",
    button: "Pause",
  },
  disable: {
    title: "Turn this rule off?",
    message: "It will stop running, and any suggestions still waiting for you will be cancelled.",
    button: "Turn off",
  },
  delete: {
    title: "Delete this rule?",
    message: "This cannot be undone. A rule that has already run cannot be deleted; turn it off instead.",
    button: "Delete",
  },
};

// R-06: configuration exactly as stored, plus the lifecycle actions.
export function RuleDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { session } = useAuth();
  const userId = session?.user.id;
  const enabled = Boolean(userId) && Boolean(id);
  const [actionError, setActionError] = useState<string | null>(null);
  const guard = useRef(createSubmitGuard()).current;

  const ruleQuery = useQuery({
    queryKey: userId ? financialRuleKeys.ruleDetail(userId, id) : SIGNED_OUT_KEY,
    queryFn: ({ signal }) => financialRulesService.getRule(id, signal),
    enabled,
  });
  const accounts = useQuery({ queryKey: ["accounts", userId], queryFn: getAccounts, enabled });
  const goals = useQuery({ queryKey: ["goals", userId], queryFn: getGoals, enabled });
  const budgets = useQuery({ queryKey: ["budgets", userId], queryFn: getBudgets, enabled });

  const actionMutation = useMutation({
    mutationFn: async (input: { rule: FinancialRule; action: RuleAction | "delete" }) => {
      if (input.action === "delete") {
        await runner.remove(input.rule);

        return null;
      }

      return runner.run(input.rule, input.action);
    },
    onSuccess: async (updated, input) => {
      if (userId) {
        await applyRuleChangeInvalidation(
          queryClient,
          userId,
          input.action === "delete"
            ? { kind: "deleted", rule: input.rule }
            : { kind: "status", rule: updated ?? input.rule, action: input.action },
        );
      }

      if (input.action === "delete") {
        router.replace("/rules");
      }
    },
    onError: (error) => {
      setActionError(describeRuleError(error, "Unable to change the rule.", { mutation: true }).message);

      // The stored state may differ from what is on screen (e.g. a 409).
      if (userId) {
        void queryClient.invalidateQueries({ queryKey: [...financialRuleKeys.rulesFamily(userId)] });
      }
    },
    onSettled: () => guard.leave(),
  });

  function perform(rule: FinancialRule, action: RuleAction | "delete") {
    if (!guard.tryEnter()) {
      return;
    }

    setActionError(null);
    actionMutation.mutate({ rule, action });
  }

  function requestAction(rule: FinancialRule, action: RuleAction | "delete") {
    if (action === "enable") {
      perform(rule, action);

      return;
    }

    const text = CONFIRM_TEXT[action];

    Alert.alert(text.title, text.message, [
      { text: "Cancel", style: "cancel" },
      { text: text.button, style: action === "delete" ? "destructive" : "default", onPress: () => perform(rule, action) },
    ]);
  }

  if (ruleQuery.isLoading) {
    return <ActivityIndicator style={styles.loader} accessibilityLabel="Loading rule" />;
  }

  if (ruleQuery.isError || !ruleQuery.data) {
    return (
      <View style={styles.content}>
        <Text style={styles.errorText} accessibilityRole="alert">
          {describeRuleError(ruleQuery.error, "Could not load this rule.").message}
        </Text>
        <Pressable accessibilityRole="button" accessibilityLabel="Retry" style={styles.button} onPress={() => void ruleQuery.refetch()}>
          <Text style={styles.buttonText}>Retry</Text>
        </Pressable>
      </View>
    );
  }

  const rule = ruleQuery.data;
  const availability = getRuleActionAvailability(rule);
  const status = ruleStatusInfo(rule.status);
  const busy = actionMutation.isPending;
  const accountOf = (accountId: string) => (accounts.data ?? []).find((account) => account.id === accountId);
  const goalName = (goalId: string) => (goals.data ?? []).find((goal) => goal.id === goalId)?.name ?? "Unavailable Goal";

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={ruleQuery.isRefetching} onRefresh={() => void ruleQuery.refetch()} />}
      >
        <Text style={styles.title} accessibilityRole="header">{rule.name}</Text>
        <Text style={styles.secondaryText}>{ruleTypeLabel(rule.rule_type)}</Text>
        <Text style={styles.statusText}>{status.label}</Text>
        {rule.description ? <Text style={styles.secondaryText}>{rule.description}</Text> : null}

        <Text style={styles.sectionTitle} accessibilityRole="header">Settings</Text>

        {rule.rule_type !== "BUDGET_ALERT" ? (
          <Text style={styles.secondaryText}>
            Account: {accountOf(rule.source_account_id)?.name ?? "Unavailable Account"}
          </Text>
        ) : (
          <Text style={styles.secondaryText}>
            Budget: {(budgets.data ?? []).find((budget) => budget.id === rule.budget_id)?.name ?? "Unavailable Budget"}
          </Text>
        )}

        {rule.rule_type === "MINIMUM_UNALLOCATED_FLOOR" ? (
          <Text style={styles.secondaryText}>
            Minimum unallocated floor: {rule.floor_amount} {accountOf(rule.source_account_id)?.currency ?? ""}
          </Text>
        ) : null}

        {rule.rule_type === "INCOME_ALLOCATION" ? (
          <>
            <Text style={styles.secondaryText}>
              {executionModeInfo(rule.execution_mode).label}: {executionModeInfo(rule.execution_mode).description}
            </Text>
            <Text style={styles.secondaryText}>{rulePolicyLabel(rule.policy)}</Text>
            {rule.percent !== null ? <Text style={styles.secondaryText}>{rule.percent}% of each income</Text> : null}
            <Text style={styles.secondaryText}>
              Income sources: {rule.income_sources.map((source) => SOURCE_COPY[source]).join(", ")}
            </Text>
            <Text style={styles.secondaryText}>
              {rule.cap_at_target ? "Stops at each Goal's target." : "Does not stop at a Goal's target."}{" "}
              {rule.allow_partial ? "Partial reservations allowed." : "Partial reservations not allowed."}
            </Text>
            {rule.effective_from ? <Text style={styles.secondaryText}>Starts from {rule.effective_from}</Text> : null}
            <Text style={styles.sectionTitle} accessibilityRole="header">Goals</Text>
            {[...rule.targets].sort((a, b) => a.position - b.position).map((target) => (
              <Text key={target.id} style={styles.secondaryText}>
                {goalName(target.goal_id)}
                {target.amount_or_cap !== null
                  ? ` — ${rule.policy === "FIXED_PER_GOAL" ? "" : "cap "}${target.amount_or_cap} ${accountOf(rule.source_account_id)?.currency ?? ""}`
                  : ""}
              </Text>
            ))}
            <Text style={styles.helperText}>{COPY.reservationMeaning}</Text>
          </>
        ) : null}

        {actionError ? (
          <Text style={styles.errorText} accessibilityRole="alert" accessibilityLiveRegion="polite">{actionError}</Text>
        ) : null}

        <Text style={styles.sectionTitle} accessibilityRole="header">Actions</Text>

        {status.actions.includes("enable") || rule.status === "draft" ? (
          <>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={ruleActionLabel("enable")}
              accessibilityState={{ disabled: busy || !availability.enable.available, busy }}
              disabled={busy || !availability.enable.available}
              style={[styles.button, (busy || !availability.enable.available) && styles.disabledButton]}
              onPress={() => requestAction(rule, "enable")}
            >
              <Text style={styles.buttonText}>{ruleActionLabel("enable")}</Text>
            </Pressable>
            {!availability.enable.available && availability.enable.reason ? (
              <Text style={styles.helperText}>{availability.enable.reason}</Text>
            ) : null}
          </>
        ) : null}

        {(["pause", "disable"] as const).map((action) =>
          availability[action].available ? (
            <Pressable
              key={action}
              accessibilityRole="button"
              accessibilityLabel={ruleActionLabel(action)}
              accessibilityState={{ disabled: busy, busy }}
              disabled={busy}
              style={[styles.button, busy && styles.disabledButton]}
              onPress={() => requestAction(rule, action)}
            >
              <Text style={styles.buttonText}>{ruleActionLabel(action)}</Text>
            </Pressable>
          ) : null,
        )}

        <Link href={{ pathname: "/rules/[id]/edit", params: { id: rule.id } }} asChild>
          <Pressable accessibilityRole="button" accessibilityLabel="Edit rule" disabled={busy} style={styles.editButton}>
            <Text style={styles.editButtonText}>Edit rule</Text>
          </Pressable>
        </Link>

        {availability.delete.available ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Delete rule"
            accessibilityState={{ disabled: busy }}
            disabled={busy}
            style={[styles.deleteButton, busy && styles.disabledButton]}
            onPress={() => requestAction(rule, "delete")}
          >
            <Text style={styles.deleteButtonText}>Delete rule</Text>
          </Pressable>
        ) : (
          <Text style={styles.helperText}>{availability.delete.reason}</Text>
        )}

        {busy ? <ActivityIndicator style={styles.loader} accessibilityLabel="Working" /> : null}
      </ScrollView>
    </SafeAreaView>
  );
}
