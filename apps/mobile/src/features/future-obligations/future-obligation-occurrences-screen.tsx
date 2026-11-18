import { useState } from "react";
import { Link } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { QueryBoundary } from "../../components/query-states";
import { refetcherOf, useScreenRefresh } from "../../lib/screen-refresh";
import { useAuth } from "../auth/auth-context";
import { styles } from "../goals/goals.styles";
import { getReconciliationOverview } from "./future-obligation-link.service";
import type { ReconciliationOccurrence } from "./future-obligation-link.types";
import {
  LINKS_EMPTY,
  LINKS_INTRO,
  LINKS_TITLE,
  LINK_MEANING,
  occurrenceAccessibilityLabel,
  occurrenceRowLines,
  occurrenceSections,
  occurrenceTitle,
} from "./future-obligation-link-view";

function OccurrenceRow({ occurrence }: { occurrence: ReconciliationOccurrence }) {
  return (
    <Link
      href={{
        pathname: "/goals/bills/occurrence",
        params: { obligationId: occurrence.obligation_id, dueDate: occurrence.due_date },
      }}
      asChild
    >
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={occurrenceAccessibilityLabel(occurrence)}
        style={styles.card}
      >
        <Text style={styles.name}>{occurrenceTitle(occurrence)}</Text>

        {occurrenceRowLines(occurrence).map((line) => (
          <Text key={line} style={styles.overviewText}>
            {line}
          </Text>
        ))}
      </Pressable>
    </Link>
  );
}

// VF-GOALS-PLANNING-002C2: "Linked expenses". The dates of the user's bills (the last
// three months, this month and the next 12 months) with whether an expense is
// linked to each. A link only records that an expense you chose goes with a date: it
// pays nothing and changes no balance, and nothing is matched automatically. Every
// date, amount and status is the backend's.
export function FutureObligationOccurrencesScreen() {
  const { session } = useAuth();
  const [showAllUpcoming, setShowAllUpcoming] = useState(false);

  const overviewQuery = useQuery({
    queryKey: ["future-obligations", session?.user.id, "reconciliation"],
    queryFn: ({ signal }) => getReconciliationOverview(signal),
    enabled: Boolean(session),
  });

  const refresh = useScreenRefresh(() => [refetcherOf(overviewQuery)]);

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refresh.refreshing} onRefresh={refresh.onRefresh} />}
      >
        <Text style={styles.title} accessibilityRole="header">
          {LINKS_TITLE}
        </Text>
        <Text style={styles.overviewText}>{LINKS_INTRO}</Text>
        <Text style={styles.overviewHelperText}>{LINK_MEANING}</Text>

        <QueryBoundary
          query={overviewQuery}
          what="bill dates"
          isEmpty={(overview) => overview.occurrences.length === 0}
          empty={LINKS_EMPTY}
        >
          {(overview) => {
            const sections = occurrenceSections(overview, showAllUpcoming);

            return (
              <View>
                <Text style={styles.overviewLabel} accessibilityRole="header">
                  Coming up
                </Text>
                {sections.upcoming.length === 0 ? (
                  <Text style={styles.overviewText}>No bill dates are coming up.</Text>
                ) : (
                  <View style={styles.list}>
                    {sections.upcoming.map((occurrence) => (
                      <OccurrenceRow key={`${occurrence.obligation_id}-${occurrence.due_date}`} occurrence={occurrence} />
                    ))}
                  </View>
                )}

                {sections.hiddenUpcoming > 0 ? (
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={`Show ${sections.hiddenUpcoming} more bill dates`}
                    style={styles.editButton}
                    onPress={() => setShowAllUpcoming(true)}
                  >
                    <Text style={styles.editButtonText}>Show {sections.hiddenUpcoming} more</Text>
                  </Pressable>
                ) : null}

                <Text style={styles.overviewLabel} accessibilityRole="header">
                  Recent
                </Text>
                {sections.recent.length === 0 ? (
                  <Text style={styles.overviewText}>No bill dates in the last three months.</Text>
                ) : (
                  <View style={styles.list}>
                    {sections.recent.map((occurrence) => (
                      <OccurrenceRow key={`${occurrence.obligation_id}-${occurrence.due_date}`} occurrence={occurrence} />
                    ))}
                  </View>
                )}
              </View>
            );
          }}
        </QueryBoundary>
      </ScrollView>
    </SafeAreaView>
  );
}
