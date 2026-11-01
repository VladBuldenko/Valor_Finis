import { useRef, useState } from "react";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  SafeAreaView,
  ScrollView,
  Text,
} from "react-native";

import { useAuth } from "../auth/auth-context";
import { createSubmitGuard } from "./financial-rule-actions";
import { COPY } from "./financial-rule-copy";
import { describeRuleError } from "./financial-rule-errors";
import { applyRuleInvalidation } from "./financial-rule-invalidation";
import { financialRuleKeys } from "./financial-rule-query-keys";
import { alertLevelInfo, alertMessage } from "./financial-rule-presentation";
import { financialRulesService } from "./financial-rule.service";
import { ALERTS_PAGE_SIZE, nextAlertOffset } from "./inbox-alerts";
import { styles } from "./rules.styles";

const SIGNED_OUT = ["financial-rules", "signed-out"] as const;
const formatTime = (iso: string): string => new Date(iso).toLocaleString();

// R-10: "To review" (default) / "Reviewed", paged by hand. This feed is
// separate from the Inbox's bounded sources, so paging here can never turn the
// Dashboard indicator into `clear`.
export function AlertsScreen() {
  const queryClient = useQueryClient();
  const { session } = useAuth();
  const userId = session?.user.id;
  const [reviewed, setReviewed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const guard = useRef(createSubmitGuard()).current;

  const feed = useInfiniteQuery({
    queryKey: userId ? financialRuleKeys.alertFeed(userId, reviewed) : SIGNED_OUT,
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      financialRulesService.listAlerts({ acknowledged: reviewed, limit: ALERTS_PAGE_SIZE, offset: pageParam }, signal),
    getNextPageParam: (last, pages) =>
      nextAlertOffset(
        last,
        pages.reduce((sum, page) => sum + page.items.length, 0),
      ),
    enabled: Boolean(userId),
  });

  const acknowledge = useMutation({
    mutationFn: (alertId: string) => financialRulesService.acknowledgeAlert(alertId),
    onSuccess: async () => {
      if (userId) {
        await applyRuleInvalidation(queryClient, userId, { type: "alert_acknowledged" });
      }
    },
    onError: (failure) => {
      setError(describeRuleError(failure, "Unable to mark the alert as reviewed.", { mutation: true }).message);
    },
    onSettled: () => guard.leave(),
  });

  const pages = feed.data?.pages ?? [];
  const unavailable = pages.length > 0 && pages[0].available === false;
  const alerts = pages.flatMap((page) => page.items);

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={feed.isRefetching && !feed.isFetchingNextPage} onRefresh={() => void feed.refetch()} />}
      >
        <Text style={styles.title} accessibilityRole="header">Alerts</Text>
        <Text style={styles.helperText}>{COPY.checkedWhen}</Text>

        <Pressable
          accessibilityRole="radio"
          accessibilityState={{ checked: !reviewed }}
          accessibilityLabel="To review"
          style={[styles.typeToggleButton, !reviewed && styles.typeToggleButtonSelected]}
          onPress={() => setReviewed(false)}
        >
          <Text style={styles.typeToggleButtonText}>To review</Text>
        </Pressable>
        <Pressable
          accessibilityRole="radio"
          accessibilityState={{ checked: reviewed }}
          accessibilityLabel="Reviewed"
          style={[styles.typeToggleButton, reviewed && styles.typeToggleButtonSelected]}
          onPress={() => setReviewed(true)}
        >
          <Text style={styles.typeToggleButtonText}>Reviewed</Text>
        </Pressable>

        {feed.isLoading ? <ActivityIndicator style={styles.loader} accessibilityLabel="Loading alerts" /> : null}
        {feed.isError ? (
          <>
            <Text style={styles.errorText} accessibilityRole="alert">
              {describeRuleError(feed.error, "Could not load your alerts.").message}
            </Text>
            <Pressable accessibilityRole="button" accessibilityLabel="Retry" style={styles.button} onPress={() => void feed.refetch()}>
              <Text style={styles.buttonText}>Retry</Text>
            </Pressable>
          </>
        ) : null}
        {unavailable ? <Text style={styles.secondaryText}>{COPY.alertsUnavailable}</Text> : null}
        {feed.isSuccess && !unavailable && alerts.length === 0 ? (
          <Text style={styles.secondaryText}>{reviewed ? "No reviewed alerts." : "No alerts need your attention."}</Text>
        ) : null}
        {error ? <Text style={styles.errorText} accessibilityRole="alert" accessibilityLiveRegion="polite">{error}</Text> : null}

        {alerts.map((alert) => {
          const level = alertLevelInfo(alert.level);

          return (
            <Pressable
              key={alert.id}
              accessible
              accessibilityRole="button"
              accessibilityLabel={`${level.label}. ${alertMessage(alert)}${alert.acknowledged_at ? ". Reviewed" : ""}${alert.resolved_at ? ". Resolved" : ""}`}
              accessibilityHint={alert.acknowledged_at ? undefined : "Marks this alert as reviewed"}
              disabled={alert.acknowledged_at !== null || acknowledge.isPending}
              style={styles.card}
              onPress={() => {
                if (!guard.tryEnter()) {
                  return;
                }

                setError(null);
                acknowledge.mutate(alert.id);
              }}
            >
              <Text style={styles.statusText}>{level.label}</Text>
              <Text style={styles.secondaryText}>{alertMessage(alert)}</Text>
              <Text style={styles.helperText}>Raised {formatTime(alert.created_at)}</Text>
              {alert.resolved_at ? <Text style={styles.helperText}>Resolved {formatTime(alert.resolved_at)}</Text> : null}
              {alert.acknowledged_at ? (
                <Text style={styles.helperText}>Reviewed {formatTime(alert.acknowledged_at)}</Text>
              ) : (
                <Text style={styles.buttonText}>Mark as reviewed</Text>
              )}
            </Pressable>
          );
        })}

        {feed.hasNextPage ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Load more alerts"
            accessibilityState={{ disabled: feed.isFetchingNextPage, busy: feed.isFetchingNextPage }}
            disabled={feed.isFetchingNextPage}
            style={styles.editButton}
            onPress={() => void feed.fetchNextPage()}
          >
            <Text style={styles.editButtonText}>Load more</Text>
          </Pressable>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}
