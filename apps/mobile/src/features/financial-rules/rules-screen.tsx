import { Link } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  SafeAreaView,
  ScrollView,
  Text,
} from "react-native";

import { useAuth } from "../auth/auth-context";
import { describeRuleError } from "./financial-rule-errors";
import { financialRuleKeys } from "./financial-rule-query-keys";
import { executionModeInfo, ruleStatusInfo, ruleTypeLabel } from "./financial-rule-presentation";
import { financialRulesService } from "./financial-rule.service";
import { styles } from "./rules.styles";

const SIGNED_OUT_KEY = ["financial-rules", "signed-out"] as const;

// R-01: the user's rules in the order the backend returns them.
export function RulesScreen() {
  const { session } = useAuth();
  const userId = session?.user.id;
  const query = useQuery({
    queryKey: userId ? financialRuleKeys.ruleList(userId) : SIGNED_OUT_KEY,
    queryFn: ({ signal }) => financialRulesService.listRules(signal),
    enabled: Boolean(userId),
  });
  const rules = query.data ?? [];

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl refreshing={query.isRefetching} onRefresh={() => void query.refetch()} />
        }
      >
        <Text style={styles.title} accessibilityRole="header">Rules</Text>

        <Link href="/rules/new" asChild>
          <Pressable accessibilityRole="button" accessibilityLabel="New rule" style={styles.button}>
            <Text style={styles.buttonText}>New rule</Text>
          </Pressable>
        </Link>

        {query.isLoading ? <ActivityIndicator style={styles.loader} accessibilityLabel="Loading rules" /> : null}

        {query.isError ? (
          <>
            <Text style={styles.errorText} accessibilityRole="alert" accessibilityLiveRegion="polite">
              {describeRuleError(query.error, "Could not load your rules.").message}
            </Text>
            <Pressable accessibilityRole="button" accessibilityLabel="Retry" style={styles.button} onPress={() => void query.refetch()}>
              <Text style={styles.buttonText}>Retry</Text>
            </Pressable>
          </>
        ) : null}

        {query.isSuccess && rules.length === 0 ? (
          <Text style={styles.secondaryText}>
            No rules yet. A rule can reserve part of your income for your Goals, or alert you when an
            Account or Budget needs attention.
          </Text>
        ) : null}

        {rules.map((rule) => {
          const status = ruleStatusInfo(rule.status);
          const mode = rule.rule_type === "INCOME_ALLOCATION" ? executionModeInfo(rule.execution_mode).label : null;

          return (
            <Link key={rule.id} href={{ pathname: "/rules/[id]", params: { id: rule.id } }} asChild>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`${rule.name}. ${ruleTypeLabel(rule.rule_type)}. ${status.label}${mode ? `. ${mode}` : ""}`}
                style={styles.card}
              >
                <Text style={styles.name}>{rule.name}</Text>
                <Text style={styles.secondaryText}>{ruleTypeLabel(rule.rule_type)}</Text>
                <Text style={styles.statusText}>{status.label}</Text>
                {mode ? <Text style={styles.secondaryText}>{mode}</Text> : null}
              </Pressable>
            </Link>
          );
        })}
      </ScrollView>
    </SafeAreaView>
  );
}
