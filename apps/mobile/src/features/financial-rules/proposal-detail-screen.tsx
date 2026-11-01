import { useRef, useState } from "react";
import { useLocalSearchParams } from "expo-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  RefreshControl,
  SafeAreaView,
  ScrollView,
  Text,
} from "react-native";

import { isCurrentQueryClient } from "../../lib/session-runtime";
import { useAuth } from "../auth/auth-context";
import { createSubmitGuard } from "./financial-rule-actions";
import { describeRuleError } from "./financial-rule-errors";
import { financialRuleKeys } from "./financial-rule-query-keys";
import { proposalStatusInfo, isProposalActionable } from "./financial-rule-presentation";
import { financialRulesService } from "./financial-rule.service";
import type { ProposalDecision } from "./financial-rule-presentation";
import {
  CONFIRM_DIALOG,
  HOLD_EXPLANATION,
  REJECT_DIALOG,
  decideProposal,
  type DecisionResult,
} from "./inbox-proposal-actions";
import { styles } from "./rules.styles";

const SIGNED_OUT = ["financial-rules", "signed-out"] as const;
const formatTime = (iso: string): string => new Date(iso).toLocaleString();

function resultMessage(result: DecisionResult): string {
  switch (result.kind) {
    case "decided":
    case "unknown_resolved":
      return result.outcome.matchesRequest
        ? result.outcome.message
        : `${result.outcome.message} This is not what you asked for.`;
    case "stale":
    case "unknown_pending":
      return result.message;
    case "failed":
      return result.info.message;
    default: {
      const exhaustive: never = result;

      return String(exhaustive);
    }
  }
}

// R-09: backend data only. The shown outcome is the RETURNED status.
export function ProposalDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const queryClient = useQueryClient();
  const { session } = useAuth();
  const userId = session?.user.id;
  const guard = useRef(createSubmitGuard()).current;
  const [result, setResult] = useState<DecisionResult | null>(null);
  const key = userId ? financialRuleKeys.proposalDetail(userId, id) : SIGNED_OUT;

  const query = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => financialRulesService.getProposal(id, signal),
    enabled: Boolean(userId) && Boolean(id),
  });

  const decision = useMutation({
    mutationFn: (kind: ProposalDecision) =>
      decideProposal({
        decision: kind,
        userId: userId as string,
        send: () =>
          kind === "confirm" ? financialRulesService.confirmProposal(id) : financialRulesService.rejectProposal(id),
        refetch: () => financialRulesService.getProposal(id),
        isCurrent: () => isCurrentQueryClient(queryClient),
        invalidate: (keys) => Promise.all(keys.map((queryKey) => queryClient.invalidateQueries({ queryKey: [...queryKey] }))),
      }),
    onSuccess: (outcome) => {
      if (!isCurrentQueryClient(queryClient)) {
        return;
      }

      // Show the authoritative proposal the flow ended with.
      if ("proposal" in outcome && outcome.proposal) {
        queryClient.setQueryData(key, outcome.proposal);
      }

      setResult(outcome);
    },
    onSettled: () => guard.leave(),
  });

  function ask(kind: ProposalDecision) {
    const dialog = kind === "confirm" ? CONFIRM_DIALOG : REJECT_DIALOG;

    Alert.alert(dialog.title, dialog.message, [
      { text: "Cancel", style: "cancel" },
      {
        text: dialog.button,
        onPress: () => {
          // One request at a time, never repeated automatically.
          if (!userId || !guard.tryEnter()) {
            return;
          }

          setResult(null);
          decision.mutate(kind);
        },
      },
    ]);
  }

  if (query.isLoading) {
    return <ActivityIndicator style={styles.loader} accessibilityLabel="Loading suggestion" />;
  }

  if (query.isError || !query.data) {
    return (
      <SafeAreaView style={styles.container}>
        <Text style={styles.errorText} accessibilityRole="alert">
          {describeRuleError(query.error, "Could not load this suggestion.").message}
        </Text>
        <Pressable accessibilityRole="button" accessibilityLabel="Retry" style={styles.button} onPress={() => void query.refetch()}>
          <Text style={styles.buttonText}>Retry</Text>
        </Pressable>
      </SafeAreaView>
    );
  }

  const proposal = query.data;
  const status = proposalStatusInfo(proposal.status);
  const busy = decision.isPending;
  const actionable = isProposalActionable(proposal.status);
  const showApplied = proposal.status === "executed" || proposal.status === "executed_partial";

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={query.isRefetching} onRefresh={() => void query.refetch()} />}
      >
        <Text style={styles.title} accessibilityRole="header">{proposal.rule_name}</Text>
        <Text style={styles.statusText}>{status.label}</Text>
        <Text style={styles.helperText}>{HOLD_EXPLANATION}</Text>

        <Text style={styles.sectionTitle} accessibilityRole="header">Income</Text>
        <Text style={styles.secondaryText}>
          {proposal.source_amount} {proposal.source_currency}, received {proposal.source_received_at}
        </Text>
        {proposal.account_id !== null ? (
          <Text style={styles.secondaryText}>Account currency: {proposal.currency}</Text>
        ) : null}

        <Text style={styles.sectionTitle} accessibilityRole="header">Suggested for your Goals</Text>
        {proposal.items.map((item) => (
          <Text
            key={item.id}
            style={styles.secondaryText}
            accessibilityLabel={`${item.goal_name}. Planned ${item.planned_amount} ${proposal.currency}${showApplied && item.applied_amount !== null ? `. Applied ${item.applied_amount} ${proposal.currency}` : ""}`}
          >
            {item.goal_name}: planned {item.planned_amount} {proposal.currency}
            {showApplied && item.applied_amount !== null ? `, applied ${item.applied_amount} ${proposal.currency}` : ""}
          </Text>
        ))}
        <Text style={styles.name}>Planned total: {proposal.planned_total} {proposal.currency}</Text>
        {proposal.status === "awaiting_confirmation" && proposal.confirm_capacity !== null ? (
          <Text style={styles.secondaryText}>
            Available for this suggestion now: {proposal.confirm_capacity} {proposal.currency}
          </Text>
        ) : null}
        <Text style={styles.helperText}>
          {proposal.status === "awaiting_confirmation" ? "Expires" : "Expiry was"} {formatTime(proposal.expires_at)}
        </Text>

        {result ? (
          <Text style={styles.noticeText} accessibilityLiveRegion="polite" accessibilityRole="alert">
            {resultMessage(result)}
          </Text>
        ) : null}

        {actionable ? (
          <>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Confirm suggestion"
              accessibilityState={{ disabled: busy, busy }}
              disabled={busy}
              style={[styles.button, busy && styles.disabledButton]}
              onPress={() => ask("confirm")}
            >
              <Text style={styles.buttonText}>Confirm</Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Decline suggestion"
              accessibilityState={{ disabled: busy, busy }}
              disabled={busy}
              style={[styles.editButton, busy && styles.disabledButton]}
              onPress={() => ask("reject")}
            >
              <Text style={styles.editButtonText}>Decline</Text>
            </Pressable>
          </>
        ) : null}
        {busy ? <ActivityIndicator style={styles.loader} accessibilityLabel="Working" /> : null}
      </ScrollView>
    </SafeAreaView>
  );
}
