import { useState } from "react";
import { Link } from "expo-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { getApiErrorMessage } from "../../api/api-error-message";
import { QueryBoundary } from "../../components/query-states";
import { refetcherOf, useScreenRefresh } from "../../lib/screen-refresh";
import { useAuth } from "../auth/auth-context";
import { styles } from "../goals/goals.styles";
import { invalidateFutureObligationQueries } from "./future-obligation-cache";
import {
  BILLS_ARCHIVED_EMPTY,
  BILLS_EMPTY,
  BILLS_INTRO,
  BILLS_NOT_PAID,
  BILLS_SCOPE,
  BILLS_SEPARATE_FROM_GOALS,
  BILLS_TITLE,
  archiveConfirmation,
  monthGroups,
  obligationLines,
  summaryLines,
  thisMonthHeadline,
} from "./future-obligation-view";
import { getFutureObligations, getUpcomingObligations, updateFutureObligation } from "./future-obligation.service";
import type { FutureObligation } from "./future-obligation.types";

type BillListView = "current" | "archived";

// VF-GOALS-PLANNING-002C1: "Upcoming bills". The bills the user entered, what falls due
// over the next 12 months, and the way to add, edit, archive and restore them. Every
// figure is the backend's; nothing is added up here, and nothing is paid, set aside or
// recorded as an expense.
export function FutureObligationsScreen() {
  const { session } = useAuth();
  const queryClient = useQueryClient();
  const [view, setView] = useState<BillListView>("current");

  const upcomingQuery = useQuery({
    queryKey: ["future-obligations", session?.user.id, "upcoming"],
    queryFn: ({ signal }) => getUpcomingObligations(signal),
    enabled: Boolean(session),
  });

  const listQuery = useQuery({
    queryKey: ["future-obligations", session?.user.id, "list"],
    queryFn: ({ signal }) => getFutureObligations(signal),
    enabled: Boolean(session),
  });

  const refresh = useScreenRefresh(() => [refetcherOf(upcomingQuery), refetcherOf(listQuery)]);

  const archiveMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: "active" | "archived" }) =>
      updateFutureObligation(id, { status }),

    onSuccess: async () => {
      await invalidateFutureObligationQueries(queryClient, session?.user.id);
    },

    onError: (mutationError) => {
      Alert.alert("Update failed", getApiErrorMessage(mutationError, "Unable to update the bill."));
    },
  });

  function handleArchive(bill: FutureObligation) {
    if (archiveMutation.isPending) {
      return;
    }

    const { title, message } = archiveConfirmation(bill.name);

    Alert.alert(title, message, [
      { text: "Cancel", style: "cancel" },
      { text: "Archive", style: "destructive", onPress: () => archiveMutation.mutate({ id: bill.id, status: "archived" }) },
    ]);
  }

  const matches = (bill: FutureObligation) => (view === "archived" ? bill.status === "archived" : bill.status === "active");

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refresh.refreshing} onRefresh={refresh.onRefresh} />}
      >
        <Text style={styles.title} accessibilityRole="header">
          {BILLS_TITLE}
        </Text>
        <Text style={styles.overviewText}>{BILLS_INTRO}</Text>

        <Link href={{ pathname: "/goals/bills/new", params: { schedule: "monthly" } }} asChild>
          <Pressable accessibilityRole="button" accessibilityLabel="Add a monthly bill" style={styles.button}>
            <Text style={styles.buttonText}>Add a monthly bill</Text>
          </Pressable>
        </Link>

        <Link href={{ pathname: "/goals/bills/new", params: { schedule: "one_time" } }} asChild>
          <Pressable accessibilityRole="button" accessibilityLabel="Add a one-time bill" style={styles.editButton}>
            <Text style={styles.editButtonText}>Add a one-time bill</Text>
          </Pressable>
        </Link>

        <Text style={styles.overviewHelperText}>{BILLS_NOT_PAID}</Text>

        <Link href="/goals/bills/links" asChild>
          <Pressable accessibilityRole="button" accessibilityLabel="Link expenses to bills" style={styles.editButton}>
            <Text style={styles.editButtonText}>Link expenses to bills</Text>
          </Pressable>
        </Link>

        <View style={styles.card}>
          <Text style={styles.name} accessibilityRole="header">
            Next 12 months
          </Text>

          <QueryBoundary query={upcomingQuery} what="upcoming bills">
            {(upcoming) => {
              const headline = thisMonthHeadline(upcoming);

              return (
                <View>
                  {headline ? (
                    <View accessible accessibilityLabel={`${headline.label}: ${headline.amount}`}>
                      <Text style={styles.overviewText}>{headline.label}</Text>
                      <Text style={styles.amount}>{headline.amount}</Text>
                    </View>
                  ) : null}

                  {summaryLines(upcoming).map((line) => (
                    <Text key={line} style={styles.overviewText}>
                      {line}
                    </Text>
                  ))}

                  {monthGroups(upcoming).map((group) => (
                    <View key={group.label}>
                      <Text style={styles.overviewLabel} accessibilityLabel={`${group.label}: ${group.value}`}>
                        {group.label}: {group.value}
                      </Text>
                      {group.items.map((item) => (
                        <Text
                          key={`${group.label}-${item.label}`}
                          style={styles.overviewHelperText}
                          accessibilityLabel={`${item.label}: ${item.value}`}
                        >
                          {item.label}: {item.value}
                        </Text>
                      ))}
                    </View>
                  ))}

                  <Text style={styles.overviewHelperText}>{BILLS_SCOPE}</Text>
                  <Text style={styles.overviewHelperText}>{BILLS_SEPARATE_FROM_GOALS}</Text>
                </View>
              );
            }}
          </QueryBoundary>
        </View>

        <View style={styles.typeToggleRow}>
          {(["current", "archived"] as const).map((option) => (
            <Pressable
              key={option}
              accessibilityRole="button"
              accessibilityState={{ selected: view === option }}
              style={[styles.typeToggleButton, view === option && styles.typeToggleButtonSelected]}
              onPress={() => setView(option)}
            >
              <Text style={[styles.typeToggleButtonText, view === option && styles.typeToggleButtonTextSelected]}>
                {option === "current" ? "Your bills" : "Archived"}
              </Text>
            </Pressable>
          ))}
        </View>

        <QueryBoundary
          query={listQuery}
          what="bills"
          isEmpty={(bills) => !bills.some(matches)}
          empty={view === "archived" ? BILLS_ARCHIVED_EMPTY : BILLS_EMPTY}
        >
          {(bills) => (
            <View style={styles.list}>
              {bills.filter(matches).map((bill) => (
                <View key={bill.id} style={styles.card}>
                  <Text style={styles.name}>{bill.name}</Text>

                  {obligationLines(bill).map((line) => (
                    <Text key={line} style={styles.overviewText}>
                      {line}
                    </Text>
                  ))}

                  <Link href={{ pathname: "/goals/bills/[id]/edit", params: { id: bill.id } }} asChild>
                    <Pressable accessibilityRole="button" accessibilityLabel={`Edit ${bill.name}`} style={styles.editButton}>
                      <Text style={styles.editButtonText}>Edit</Text>
                    </Pressable>
                  </Link>

                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={bill.status === "archived" ? `Restore ${bill.name}` : `Archive ${bill.name}`}
                    disabled={archiveMutation.isPending}
                    style={styles.editButton}
                    onPress={() =>
                      bill.status === "archived"
                        ? archiveMutation.mutate({ id: bill.id, status: "active" })
                        : handleArchive(bill)
                    }
                  >
                    <Text style={styles.editButtonText}>{bill.status === "archived" ? "Restore" : "Archive"}</Text>
                  </Pressable>
                </View>
              ))}
            </View>
          )}
        </QueryBoundary>
      </ScrollView>
    </SafeAreaView>
  );
}
