import { useState } from "react";
import { Link, useLocalSearchParams } from "expo-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { getApiErrorMessage } from "../../api/api-error-message";
import { QueryBoundary } from "../../components/query-states";
import { refetcherOf, useScreenRefresh } from "../../lib/screen-refresh";
import { useAuth } from "../auth/auth-context";
import { styles } from "../goals/goals.styles";
import { invalidateReconciliationQueries } from "./future-obligation-link-cache";
import {
  getOccurrenceCandidates,
  getReconciliationOverview,
  linkOccurrence,
  unlinkOccurrence,
} from "./future-obligation-link.service";
import type { CandidateExpense, ReconciliationOccurrence } from "./future-obligation-link.types";
import {
  LINK_MEANING,
  NOT_LINKED_NOTE,
  OCCURRENCE_GONE,
  PICKER_RULES,
  PICKER_TITLE,
  candidateLines,
  exclusionLines,
  findOccurrence,
  linkConfirmation,
  noCandidatesMessage,
  occurrenceAmount,
  occurrenceTitle,
  statusLabel,
  unlinkConfirmation,
} from "./future-obligation-link-view";

// VF-GOALS-PLANNING-002C2: one bill date. Shows its due date and expected amount, whether
// an expense is linked, and lets the user link an existing expense they choose, look
// at the linked expense, or remove a link that is wrong. A link is relationship
// metadata only: it creates no expense, pays nothing, changes no balance and is not
// checked with any bank. Every value, including what can be linked, is the backend's.
export function FutureObligationOccurrenceScreen() {
  const { obligationId, dueDate } = useLocalSearchParams<{ obligationId: string; dueDate: string }>();
  const { session } = useAuth();
  const queryClient = useQueryClient();
  const userId = session?.user.id;
  const [picking, setPicking] = useState(false);

  const overviewQuery = useQuery({
    queryKey: ["future-obligations", userId, "reconciliation"],
    queryFn: ({ signal }) => getReconciliationOverview(signal),
    enabled: Boolean(session),
  });

  // Read only while the picker is open: a date that is not being linked never loads it.
  const candidatesQuery = useQuery({
    queryKey: ["future-obligations", userId, "candidates", obligationId, dueDate],
    queryFn: ({ signal }) => getOccurrenceCandidates(obligationId, dueDate, signal),
    enabled: Boolean(session) && picking && Boolean(obligationId) && Boolean(dueDate),
  });

  const refresh = useScreenRefresh(() => [refetcherOf(overviewQuery)]);

  const linkMutation = useMutation({
    mutationFn: (expenseId: string) => linkOccurrence(obligationId, { due_date: dueDate, expense_id: expenseId }),

    onSuccess: async () => {
      setPicking(false);
      await invalidateReconciliationQueries(queryClient, userId);
    },

    onError: async (mutationError) => {
      Alert.alert("Link failed", getApiErrorMessage(mutationError, "Unable to link the expense."));
      // The refusal may mean what is on screen is stale: re-read it.
      await invalidateReconciliationQueries(queryClient, userId);
    },
  });

  const unlinkMutation = useMutation({
    mutationFn: (linkId: string) => unlinkOccurrence(obligationId, linkId),

    onSuccess: async () => {
      await invalidateReconciliationQueries(queryClient, userId);
    },

    onError: async (mutationError) => {
      Alert.alert("Remove failed", getApiErrorMessage(mutationError, "Unable to remove the link."));
      await invalidateReconciliationQueries(queryClient, userId);
    },
  });

  const busy = linkMutation.isPending || unlinkMutation.isPending;

  function handleChoose(occurrence: ReconciliationOccurrence, candidate: CandidateExpense) {
    if (busy) {
      return;
    }

    const { title, message } = linkConfirmation(occurrence, candidate);

    Alert.alert(title, message, [
      { text: "Cancel", style: "cancel" },
      { text: "Link", onPress: () => linkMutation.mutate(candidate.expense_id) },
    ]);
  }

  function handleUnlink(occurrence: ReconciliationOccurrence) {
    const linked = occurrence.linked_expense;

    if (busy || linked === null) {
      return;
    }

    const { title, message } = unlinkConfirmation(occurrence);

    Alert.alert(title, message, [
      { text: "Cancel", style: "cancel" },
      { text: "Remove link", style: "destructive", onPress: () => unlinkMutation.mutate(linked.link_id) },
    ]);
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refresh.refreshing} onRefresh={refresh.onRefresh} />}
      >
        <QueryBoundary query={overviewQuery} what="bill date" isEmpty={() => false}>
          {(overview) => {
            const occurrence = findOccurrence(overview, obligationId, dueDate);

            if (occurrence === null) {
              return <Text style={styles.overviewText}>{OCCURRENCE_GONE}</Text>;
            }

            const linked = occurrence.linked_expense;

            return (
              <View>
                <Text style={styles.title} accessibilityRole="header">
                  {occurrenceTitle(occurrence)}
                </Text>
                <Text style={styles.overviewText}>Expected amount</Text>
                <Text style={styles.amount}>{occurrenceAmount(occurrence)}</Text>
                <Text style={styles.overviewLabel}>{statusLabel(occurrence)}</Text>
                {occurrence.obligation_status === "archived" ? (
                  <Text style={styles.overviewHelperText}>This bill is archived.</Text>
                ) : null}

                {linked !== null ? (
                  <View style={styles.card}>
                    <Text style={styles.name}>{linked.title}</Text>
                    <Text style={styles.overviewText}>Recorded on {linked.expense_date}</Text>
                    <Text style={styles.overviewText}>{`${linked.amount} ${linked.currency}`}</Text>

                    <Link href={{ pathname: "/expenses/[id]", params: { id: linked.expense_id } }} asChild>
                      <Pressable
                        accessibilityRole="button"
                        accessibilityLabel={`View expense ${linked.title}`}
                        style={styles.editButton}
                      >
                        <Text style={styles.editButtonText}>View expense</Text>
                      </Pressable>
                    </Link>

                    <Pressable
                      accessibilityRole="button"
                      accessibilityLabel="Remove link"
                      disabled={busy}
                      style={styles.editButton}
                      onPress={() => handleUnlink(occurrence)}
                    >
                      <Text style={styles.editButtonText}>Remove link</Text>
                    </Pressable>
                  </View>
                ) : (
                  <View>
                    <Text style={styles.overviewHelperText}>{NOT_LINKED_NOTE}</Text>

                    {occurrence.obligation_status === "active" ? (
                      <Pressable
                        accessibilityRole="button"
                        accessibilityLabel="Link existing expense"
                        accessibilityState={{ expanded: picking }}
                        disabled={busy}
                        style={styles.button}
                        onPress={() => setPicking((open) => !open)}
                      >
                        <Text style={styles.buttonText}>{picking ? "Hide expenses" : "Link existing expense"}</Text>
                      </Pressable>
                    ) : null}

                    {picking ? (
                      <View style={styles.card}>
                        <Text style={styles.name} accessibilityRole="header">
                          {PICKER_TITLE}
                        </Text>
                        <Text style={styles.overviewHelperText}>{PICKER_RULES}</Text>

                        <QueryBoundary query={candidatesQuery} what="expenses to link" isEmpty={() => false}>
                          {(candidates) => (
                            <View>
                              {candidates.candidates.length === 0 ? (
                                <Text style={styles.overviewText}>{noCandidatesMessage(candidates)}</Text>
                              ) : (
                                candidates.candidates.map((candidate) => (
                                  <Pressable
                                    key={candidate.expense_id}
                                    accessibilityRole="button"
                                    accessibilityLabel={`Link ${candidate.title}, ${candidate.expense_date}`}
                                    disabled={busy}
                                    style={styles.card}
                                    onPress={() => handleChoose(occurrence, candidate)}
                                  >
                                    {candidateLines(candidate).map((line, index) => (
                                      <Text key={line} style={index === 0 ? styles.name : styles.overviewText}>
                                        {line}
                                      </Text>
                                    ))}
                                  </Pressable>
                                ))
                              )}

                              {exclusionLines(candidates).map((line) => (
                                <Text key={line} style={styles.overviewHelperText}>
                                  {line}
                                </Text>
                              ))}
                            </View>
                          )}
                        </QueryBoundary>
                      </View>
                    ) : null}
                  </View>
                )}

                <Text style={styles.overviewHelperText}>{LINK_MEANING}</Text>
              </View>
            );
          }}
        </QueryBoundary>
      </ScrollView>
    </SafeAreaView>
  );
}
