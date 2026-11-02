import { useEffect } from "react";
import { Link } from "expo-router";
import { useQueryClient } from "@tanstack/react-query";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  SafeAreaView,
  ScrollView,
  Text,
  View,
} from "react-native";

import { COPY } from "./financial-rule-copy";
import { describeRuleError } from "./financial-rule-errors";
import {
  alertLevelInfo,
  alertMessage,
  executionStatusInfo,
  reasonText,
} from "./financial-rule-presentation";
import { inboxIndicatorPresentation } from "./inbox-data";
import { styles } from "./rules.styles";
import { useRulesEvaluation } from "./rules-evaluation-provider";
import { useInboxData } from "./use-inbox-data";

const formatTime = (iso: string): string => new Date(iso).toLocaleString();

function SectionRetry({ label, onRetry }: { label: string; onRetry: () => void }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`Retry ${label}`}
      style={styles.button}
      onPress={onRetry}
    >
      <Text style={styles.buttonText}>Retry</Text>
    </Pressable>
  );
}

// R-08: three independently loaded sources. A failing source never blanks the
// others; each has its own loading, empty and error-with-Retry state.
export function InboxScreen() {
  const queryClient = useQueryClient();
  const { request } = useRulesEvaluation();
  const { proposals, alerts, executions, evaluation, indicator } = useInboxData();
  const presentation = inboxIndicatorPresentation(indicator);

  // Opening the Inbox asks for an evaluation (debounced, cooldown-limited).
  useEffect(() => {
    request("inbox_open");
  }, [request]);

  const proposalItems = proposals.data?.items ?? [];
  const alertItems = alerts.data?.items ?? [];
  const alertsUnavailable = alerts.isSuccess && alerts.data?.available === false;

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl
            refreshing={false}
            onRefresh={() => {
              void queryClient.invalidateQueries({ queryKey: ["rule-proposals"] });
              void queryClient.invalidateQueries({ queryKey: ["rule-alerts"] });
              void queryClient.invalidateQueries({ queryKey: ["rule-executions"] });
              request("inbox_open");
            }}
          />
        }
      >
        <Text style={styles.title} accessibilityRole="header">Inbox</Text>
        <Text style={styles.statusText} accessibilityLabel={presentation.accessibilityLabel}>
          {presentation.marker}
        </Text>
        <Text style={styles.helperText}>{COPY.checkedWhen}</Text>

        {evaluation.status === "failed" ? (
          <Text style={styles.errorText} accessibilityLiveRegion="polite" accessibilityRole="alert">
            Could not check your rules just now. Try again.
          </Text>
        ) : null}
        {evaluation.status === "incomplete" ? (
          <Text style={styles.noticeText} accessibilityLiveRegion="polite">{COPY.evaluationBlocked}</Text>
        ) : null}

        <Text style={styles.sectionTitle} accessibilityRole="header">Waiting for you</Text>
        {proposals.isLoading ? <ActivityIndicator style={styles.loader} accessibilityLabel="Loading suggestions" /> : null}
        {proposals.isError ? (
          <>
            <Text style={styles.errorText} accessibilityRole="alert">
              {describeRuleError(proposals.error, "Could not load your suggestions.").message}
            </Text>
            <SectionRetry label="suggestions" onRetry={() => void proposals.refetch()} />
          </>
        ) : null}
        {proposals.isSuccess && proposalItems.length === 0 ? (
          <Text style={styles.secondaryText}>Nothing is waiting for you.</Text>
        ) : null}
        {proposalItems.map((proposal) => (
          <Link key={proposal.id} href={{ pathname: "/inbox/proposals/[id]", params: { id: proposal.id } }} asChild>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={`${proposal.rule_name}. Suggested ${proposal.planned_total} ${proposal.currency}. Expires ${formatTime(proposal.expires_at)}`}
              style={styles.card}
            >
              <Text style={styles.name}>{proposal.rule_name}</Text>
              <Text style={styles.secondaryText}>Suggested: {proposal.planned_total} {proposal.currency}</Text>
              <Text style={styles.helperText}>Expires {formatTime(proposal.expires_at)}</Text>
            </Pressable>
          </Link>
        ))}
        {proposals.isSuccess && proposals.data && !proposals.data.complete ? (
          <Text style={styles.noticeText}>More suggestions are waiting than are shown here.</Text>
        ) : null}

        <Text style={styles.sectionTitle} accessibilityRole="header">Alerts</Text>
        {alerts.isLoading ? <ActivityIndicator style={styles.loader} accessibilityLabel="Loading alerts" /> : null}
        {alerts.isError ? (
          <>
            <Text style={styles.errorText} accessibilityRole="alert">
              {describeRuleError(alerts.error, "Could not load your alerts.").message}
            </Text>
            <SectionRetry label="alerts" onRetry={() => void alerts.refetch()} />
          </>
        ) : null}
        {alertsUnavailable ? <Text style={styles.secondaryText}>{COPY.alertsUnavailable}</Text> : null}
        {alerts.isSuccess && !alertsUnavailable && alertItems.length === 0 ? (
          <Text style={styles.secondaryText}>No alerts need your attention.</Text>
        ) : null}
        {alertItems.map((alert) => (
          <View key={alert.id} style={styles.card} accessible accessibilityLabel={`${alertLevelInfo(alert.level).label}. ${alertMessage(alert)}`}>
            <Text style={styles.statusText}>{alertLevelInfo(alert.level).label}</Text>
            <Text style={styles.secondaryText}>{alertMessage(alert)}</Text>
          </View>
        ))}
        {alerts.isSuccess && alerts.data && !alerts.data.complete && !alertsUnavailable ? (
          <Text style={styles.noticeText}>More alerts are waiting than are shown here.</Text>
        ) : null}
        <Link href="/inbox/alerts" asChild>
          <Pressable accessibilityRole="button" accessibilityLabel="See all alerts" style={styles.editButton}>
            <Text style={styles.editButtonText}>See all alerts</Text>
          </Pressable>
        </Link>

        <Text style={styles.sectionTitle} accessibilityRole="header">Recent activity</Text>
        {executions.isLoading ? <ActivityIndicator style={styles.loader} accessibilityLabel="Loading recent activity" /> : null}
        {executions.isError ? (
          <>
            <Text style={styles.errorText} accessibilityRole="alert">
              {describeRuleError(executions.error, "Could not load recent activity.").message}
            </Text>
            <SectionRetry label="recent activity" onRetry={() => void executions.refetch()} />
          </>
        ) : null}
        {executions.isSuccess && (executions.data?.items.length ?? 0) === 0 ? (
          <Text style={styles.secondaryText}>No recent activity.</Text>
        ) : null}
        {(executions.data?.items ?? []).map((execution) => {
          const status = executionStatusInfo(execution.status);
          const reason = reasonText(execution.reason_code);

          return (
            <View
              key={execution.id}
              style={styles.card}
              accessible
              accessibilityLabel={`${status.label}. Income ${execution.source_amount} ${execution.source_currency}${reason ? `. ${reason}` : ""}`}
            >
              <Text style={styles.statusText}>{status.label}</Text>
              <Text style={styles.secondaryText}>Income {execution.source_amount} {execution.source_currency}</Text>
              {reason ? <Text style={styles.helperText}>{reason}</Text> : null}
            </View>
          );
        })}
        <Link href="/rules/history" asChild>
          <Pressable accessibilityRole="button" accessibilityLabel="See all activity" style={styles.editButton}>
            <Text style={styles.editButtonText}>See all activity</Text>
          </Pressable>
        </Link>
      </ScrollView>
    </SafeAreaView>
  );
}
