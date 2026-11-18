import { Link } from "expo-router";
import { Pressable, Text, View } from "react-native";
import type { UseQueryResult } from "@tanstack/react-query";

import { QueryBoundary } from "../../components/query-states";
import { styles } from "../goals/goals.styles";
import {
  BILLS_NOT_PAID,
  BILLS_SEPARATE_FROM_GOALS,
  BILLS_TITLE,
  goalsCardLines,
  hasNoUpcomingBills,
  thisMonthHeadline,
} from "./future-obligation-view";
import type { UpcomingObligations } from "./future-obligation.types";

// VF-GOALS-PLANNING-002C1: the compact "Upcoming bills" card on the Goals screen, next
// to Savings plans. The two are different planning categories and their amounts are
// never combined or compared here. Read-only: every figure is the backend's
// GET /future-obligations/upcoming (the query is owned by the screen so its
// pull-to-refresh re-reads it), with its own loading, error and Retry, so a failed
// read never hides the Goals below it.
export function UpcomingBillsCard({ query }: { query: UseQueryResult<UpcomingObligations> }) {
  return (
    <View style={styles.card}>
      <Text style={styles.name} accessibilityRole="header">
        {BILLS_TITLE}
      </Text>

      <QueryBoundary query={query} what="upcoming bills">
        {(upcoming) => {
          const headline = thisMonthHeadline(upcoming);

          return (
            <View>
              {hasNoUpcomingBills(upcoming) ? (
                <Text style={styles.overviewText}>No upcoming bills yet. Add the bills you know are coming.</Text>
              ) : (
                <View>
                  {headline ? (
                    <View accessible accessibilityLabel={`${headline.label}: ${headline.amount}`}>
                      <Text style={styles.overviewText}>{headline.label}</Text>
                      <Text style={styles.amount}>{headline.amount}</Text>
                    </View>
                  ) : null}

                  {goalsCardLines(upcoming).map((line) => (
                    <Text key={line} style={styles.overviewText}>
                      {line}
                    </Text>
                  ))}
                </View>
              )}

              <Text style={styles.overviewHelperText}>{BILLS_SEPARATE_FROM_GOALS}</Text>
              <Text style={styles.overviewHelperText}>{BILLS_NOT_PAID}</Text>
            </View>
          );
        }}
      </QueryBoundary>

      <Link href="/goals/bills" asChild>
        <Pressable accessibilityRole="button" accessibilityLabel="Open upcoming bills" style={styles.editButton}>
          <Text style={styles.editButtonText}>Open upcoming bills</Text>
        </Pressable>
      </Link>

      <Link href={{ pathname: "/goals/bills/new", params: { schedule: "monthly" } }} asChild>
        <Pressable accessibilityRole="button" accessibilityLabel="Add a bill" style={styles.editButton}>
          <Text style={styles.editButtonText}>Add a bill</Text>
        </Pressable>
      </Link>
    </View>
  );
}
