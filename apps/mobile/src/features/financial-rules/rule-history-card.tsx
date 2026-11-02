import { Link } from "expo-router";
import { Pressable, Text, View } from "react-native";

import { COPY } from "./financial-rule-copy";
import { HISTORY_COPY, type HistoryCardView } from "./execution-history-view";
import { styles } from "./rules.styles";

// One execution (R-11). The header is the only control that toggles the card;
// the details are read-only text. The outcome is always written out, never
// carried by colour.
export function RuleHistoryCard({
  view,
  expanded,
  onToggle,
}: {
  view: HistoryCardView;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <View style={styles.card}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={view.summaryLabel}
        accessibilityHint={expanded ? "Hides the details" : "Shows the details"}
        accessibilityState={{ expanded }}
        onPress={onToggle}
      >
        <Text style={styles.statusText}>{view.statusLabel}</Text>
        <Text style={styles.name}>{view.heading}</Text>
        <Text style={styles.helperText}>{view.ranAt}</Text>
        {view.decidedAt ? <Text style={styles.helperText}>{view.decidedAt}</Text> : null}
        <Text style={styles.secondaryText}>{view.explanation}</Text>
        {view.reason ? <Text style={styles.secondaryText}>{view.reason}</Text> : null}
        {view.nothingReserved ? <Text style={styles.secondaryText}>{view.nothingReserved}</Text> : null}
        <Text style={styles.editButtonText}>{expanded ? "Hide details" : "Show details"}</Text>
      </Pressable>

      {view.awaitingDecision ? (
        <Link href="/inbox" asChild>
          <Pressable accessibilityRole="button" accessibilityLabel={HISTORY_COPY.openInbox} style={styles.editButton}>
            <Text style={styles.editButtonText}>{HISTORY_COPY.openInbox}</Text>
          </Pressable>
        </Link>
      ) : null}

      {expanded ? (
        <View accessibilityLabel={`Details. ${view.rule}`}>
          <Text style={styles.sectionTitle} accessibilityRole="header">Rule</Text>
          <Text style={styles.secondaryText}>{view.rule} (current name)</Text>
          <Text style={styles.helperText}>{view.version}</Text>

          <Text style={styles.sectionTitle} accessibilityRole="header">Goals</Text>
          {view.goalsNote ? <Text style={styles.secondaryText}>{view.goalsNote}</Text> : null}
          {view.goals.map((goal) => (
            <View
              key={goal.key}
              style={styles.targetRow}
              accessible
              accessibilityLabel={`${goal.name} (current name). Planned ${goal.planned}. Applied: ${goal.applied}.${goal.reservationRecorded ? ` ${HISTORY_COPY.reservationRecorded}.` : ""}`}
            >
              <Text style={styles.name}>{goal.name} (current name)</Text>
              <Text style={styles.secondaryText}>Planned: {goal.planned}</Text>
              <Text style={styles.secondaryText}>Applied: {goal.applied}</Text>
              {goal.reservationRecorded ? <Text style={styles.helperText}>{HISTORY_COPY.reservationRecorded}</Text> : null}
            </View>
          ))}

          <Text style={styles.sectionTitle} accessibilityRole="header">Figures when it ran</Text>
          {view.figuresNote ? <Text style={styles.helperText}>{view.figuresNote}</Text> : null}
          {view.figures.map((figure) => (
            <Text key={figure.label} style={styles.secondaryText} accessibilityLabel={`${figure.label}: ${figure.value}`}>
              {figure.label}: {figure.value}
            </Text>
          ))}

          {view.activity.length > 0 ? (
            <>
              <Text style={styles.sectionTitle} accessibilityRole="header">What happened</Text>
              {view.activity.map((line, index) => (
                <Text key={`${index}-${line}`} style={styles.secondaryText}>{line}</Text>
              ))}
            </>
          ) : null}

          <Text style={styles.helperText}>{COPY.reservationMeaning}</Text>
        </View>
      ) : null}
    </View>
  );
}
