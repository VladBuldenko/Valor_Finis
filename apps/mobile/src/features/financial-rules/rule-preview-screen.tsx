import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { useLocalSearchParams, useRouter } from "expo-router";
import { skipToken, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  SafeAreaView,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";

import { isCurrentQueryClient } from "../../lib/session-runtime";
import { getAccounts } from "../accounts/account.service";
import { useAuth } from "../auth/auth-context";
import { getGoals } from "../goals/goal.service";
import {
  applyRuleChangeInvalidation,
  createRuleActionRunner,
  createSubmitGuard,
} from "./financial-rule-actions";
import { AUTO_ACTIVATION_DIALOG, activateAutoRule, autoActivationMessage, type ActivationResult } from "./auto-activation";
import { COPY, SOURCE_COPY } from "./financial-rule-copy";
import { describeRuleError } from "./financial-rule-errors";
import { financialRuleKeys } from "./financial-rule-query-keys";
import { ruleStatusInfo } from "./financial-rule-presentation";
import { financialRulesService } from "./financial-rule.service";
import { INCOME_SOURCES, type IncomeSource, type RulePreview } from "./financial-rule.types";
import { previewAuthorizations, previewKeyFor, sameInputs, type PreviewInputs } from "./preview-authorization";
import { requestRulePreview, validateSampleAmount } from "./rule-preview-flow";
import { buildPreviewView, turnOnBlockReason } from "./rule-preview-view";
import { styles } from "./rules.styles";

const SIGNED_OUT = ["financial-rules", "signed-out"] as const;

function activationMessage(result: ActivationResult): string | null {
  switch (result.kind) {
    case "activated":
      return "The automatic rule is on.";
    case "unknown_resolved":
      return "The automatic rule is on. We confirmed it after the answer was lost.";
    case "unexpected_status":
      return `The rule is now ${ruleStatusInfo(result.rule.status).label}. It was not turned on as asked.`;
    case "needs_new_preview":
      return result.message;
    case "not_checked":
      return result.info.message;
    case "failed":
      return result.info.message;
    case "unknown_pending":
      return result.message;
    case "session_changed":
      return null;
    default: {
      const exhaustive: never = result;

      return String(exhaustive);
    }
  }
}

// R-07: an example worked out by the backend. The screen never computes a
// figure. The "Turn on" control exists only here for an AUTO rule, and is
// enabled only while a valid proof of THIS viewed result exists (the runner
// checks the same proof again before anything is sent).
export function RulePreviewScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { session } = useAuth();
  const userId = session?.user.id;
  const enabled = Boolean(userId) && Boolean(id);
  const [amountText, setAmountText] = useState("");
  const [source, setSource] = useState<IncomeSource | null>(null);
  const [submitted, setSubmitted] = useState<{ ruleVersion: number; inputs: PreviewInputs } | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [activation, setActivation] = useState<ActivationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [activating, setActivating] = useState(false);
  const previewGuard = useRef(createSubmitGuard()).current;
  const activationGuard = useRef(createSubmitGuard()).current;
  const authorizations = previewAuthorizations(queryClient);
  // Re-render when a result is recorded as viewed or an authorization is revoked.
  const authorizationVersion = useSyncExternalStore(authorizations.subscribe, authorizations.getVersion);
  const runner = useMemo(
    () => createRuleActionRunner(financialRulesService, previewAuthorizations(queryClient)),
    [queryClient],
  );

  const ruleQuery = useQuery({
    queryKey: userId ? financialRuleKeys.ruleDetail(userId, id) : SIGNED_OUT,
    queryFn: ({ signal }) => financialRulesService.getRule(id, signal),
    enabled,
  });
  // Names for the Goals, and Account/Goal staleness: a change to either
  // revokes the authorization (see preview-authorization.ts).
  const goals = useQuery({ queryKey: ["goals", userId], queryFn: getGoals, enabled });
  const accounts = useQuery({ queryKey: ["accounts", userId], queryFn: getAccounts, enabled });
  const rule = ruleQuery.data;

  const previewKey =
    userId && rule && submitted
      ? previewKeyFor({ userId, ruleId: rule.id, ruleVersion: submitted.ruleVersion, inputs: submitted.inputs })
      : SIGNED_OUT;
  // Read-only observer of the cached example: it is filled by the request
  // below and marked stale when the cache is invalidated.
  const previewQuery = useQuery<RulePreview>({
    queryKey: previewKey,
    queryFn: skipToken,
    staleTime: Infinity,
  });

  const preview = submitted !== null && rule ? previewQuery.data : undefined;
  const versionChanged = submitted !== null && rule !== undefined && submitted.ruleVersion !== rule.version;
  const outOfDate = preview !== undefined && (previewQuery.isStale || versionChanged);
  const settled = !goals.isFetching && !accounts.isFetching;
  const shownVersion = submitted?.ruleVersion;
  const shownInputs = submitted?.inputs;
  const shownUpdatedAt = previewQuery.dataUpdatedAt;
  const ruleId = rule?.id;

  // "Viewed" is recorded after the current result is on screen, and only once
  // the Goal/Account figures it depends on have settled.
  useEffect(() => {
    if (!userId || !ruleId || shownVersion === undefined || !shownInputs || preview === undefined || outOfDate || !settled) {
      return;
    }

    previewAuthorizations(queryClient).markViewed({ userId, ruleId, ruleVersion: shownVersion, inputs: shownInputs });
  }, [queryClient, userId, ruleId, shownVersion, shownInputs, shownUpdatedAt, preview, outOfDate, settled]);

  const currentInputs: PreviewInputs = { amount: amountText.trim(), source };
  const inputsMatch = shownInputs !== undefined && sameInputs(shownInputs, currentInputs);
  const isAuto = rule?.rule_type === "INCOME_ALLOCATION" && rule.execution_mode === "AUTO";
  const offersEnable = rule !== undefined && ruleStatusInfo(rule.status).actions.includes("enable");
  // authorizationVersion is read so this line is re-evaluated when the store changes.
  const proof =
    authorizationVersion >= 0 &&
    userId && rule && shownVersion !== undefined && shownInputs && preview !== undefined && !outOfDate && inputsMatch
      ? authorizations.proofFor({ userId, ruleId: rule.id, ruleVersion: shownVersion, inputs: shownInputs })
      : null;

  const turnOnReason = turnOnBlockReason({
    isAutoAllocation: isAuto,
    statusOffersEnable: offersEnable,
    hasShownPreview: preview !== undefined,
    outOfDate,
    inputsMatchShown: inputsMatch,
    hasValidProof: proof !== null,
    busy: loading || activating,
  });

  const canTurnOn = turnOnReason === null;

  async function showExample() {
    if (!userId || !rule || !previewGuard.tryEnter()) {
      return;
    }

    const problem = validateSampleAmount(amountText);

    if (problem !== null) {
      previewGuard.leave();
      setMessage(problem);

      return;
    }

    setMessage(null);
    setActivation(null);
    setLoading(true);

    try {
      const result = await requestRulePreview({
        queryClient,
        userId,
        rule,
        inputs: currentInputs,
        send: (ruleIdToSend, request) => financialRulesService.previewRule(ruleIdToSend, request),
        isCurrent: () => isCurrentQueryClient(queryClient),
      });

      switch (result.kind) {
        case "ok":
          setSubmitted({ ruleVersion: rule.version, inputs: result.inputs });
          break;
        case "invalid_input":
        case "not_previewable":
          setMessage(result.message);
          break;
        case "rule_changed":
          setMessage(result.message);
          void ruleQuery.refetch();
          break;
        case "failed":
          setMessage(result.info.message);
          break;
        case "stale_session":
          break;
        default: {
          const exhaustive: never = result;

          setMessage(String(exhaustive));
        }
      }
    } finally {
      previewGuard.leave();
      setLoading(false);
    }
  }

  async function turnOn() {
    if (!userId || !rule || !shownInputs || shownVersion === undefined || !activationGuard.tryEnter()) {
      return;
    }

    setActivating(true);
    setMessage(null);

    try {
      const result = await activateAutoRule({
        rule,
        proof:
          authorizations.proofFor({ userId, ruleId: rule.id, ruleVersion: shownVersion, inputs: shownInputs }) ??
          undefined,
        run: (target, activationProof) =>
          runner.run(target, "enable", {
            proof: activationProof,
            isCurrent: () => isCurrentQueryClient(queryClient),
          }),
        readBack: (ruleIdToRead) => financialRulesService.getRule(ruleIdToRead),
        isCurrent: () => isCurrentQueryClient(queryClient),
        invalidate: (change) => applyRuleChangeInvalidation(queryClient, userId, change),
      });

      if (result.kind !== "session_changed") {
        setActivation(result);
      }

      if (result.kind === "needs_new_preview") {
        authorizations.revokeRule(rule.id);
        void ruleQuery.refetch();
      }
    } finally {
      activationGuard.leave();
      setActivating(false);
    }
  }

  function confirmTurnOn() {
    Alert.alert(AUTO_ACTIVATION_DIALOG.title, autoActivationMessage, [
      { text: "Cancel", style: "cancel" },
      { text: AUTO_ACTIVATION_DIALOG.button, onPress: () => void turnOn() },
    ]);
  }

  if (ruleQuery.isLoading) {
    return <ActivityIndicator style={styles.loader} accessibilityLabel="Loading rule" />;
  }

  if (ruleQuery.isError || !rule) {
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

  if (rule.rule_type !== "INCOME_ALLOCATION") {
    return (
      <View style={styles.content}>
        <Text style={styles.helperText}>An example is only available for rules that reserve money from income.</Text>
      </View>
    );
  }

  const view = preview ? buildPreviewView(preview, rule.name, (goalId) => (goals.data ?? []).find((goal) => goal.id === goalId)?.name ?? null) : null;
  const activated = activation?.kind === "activated" || activation?.kind === "unknown_resolved";
  const activationText = activation ? activationMessage(activation) : null;
  const amountProblem = amountText.trim() === "" ? null : validateSampleAmount(amountText);
  const canAsk = !loading && !activating && amountText.trim() !== "" && amountProblem === null;

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <Text style={styles.title} accessibilityRole="header">{rule.name}</Text>
        <Text style={styles.helperText}>
          {COPY.previewLabel}. {COPY.previewDisclaimer}
        </Text>

        <View style={styles.formGroup}>
          <Text style={styles.label}>Example income amount</Text>
          <TextInput
            style={styles.input}
            value={amountText}
            onChangeText={setAmountText}
            keyboardType="decimal-pad"
            editable={!loading && !activating}
            accessibilityLabel="Example income amount"
            placeholder="0.00"
          />
          {amountProblem ? <Text style={styles.errorText}>{amountProblem}</Text> : null}
        </View>

        <View style={styles.formGroup}>
          <Text style={styles.label} accessibilityRole="header">Income source (optional)</Text>
          <View style={styles.chipRow}>
            {[null, ...INCOME_SOURCES].map((option) => {
              const selected = source === option;
              const label = option === null ? "Not specified" : SOURCE_COPY[option];

              return (
                <Pressable
                  key={option ?? "none"}
                  accessibilityRole="radio"
                  accessibilityState={{ checked: selected, disabled: loading || activating }}
                  accessibilityLabel={label}
                  disabled={loading || activating}
                  style={[styles.chip, selected && styles.chipSelected]}
                  onPress={() => setSource(option)}
                >
                  <Text style={[styles.chipText, selected && styles.chipTextSelected]}>
                    {selected ? `✓ ${label}` : label}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </View>

        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Show example"
          accessibilityState={{ disabled: !canAsk, busy: loading }}
          disabled={!canAsk}
          style={[styles.button, !canAsk && styles.disabledButton]}
          onPress={() => void showExample()}
        >
          <Text style={styles.buttonText}>Show example</Text>
        </Pressable>
        {loading ? <ActivityIndicator style={styles.loader} accessibilityLabel="Working out the example" /> : null}

        {message ? (
          <Text style={styles.errorText} accessibilityRole="alert" accessibilityLiveRegion="polite">{message}</Text>
        ) : null}

        {view ? (
          <View style={[styles.card, outOfDate && styles.disabledButton]} accessibilityLiveRegion="polite">
            <Text style={styles.statusText}>{view.label}</Text>
            <Text style={styles.sectionTitle} accessibilityRole="header">{view.heading}</Text>
            <Text style={styles.secondaryText}>{view.ruleLine}</Text>
            <Text style={styles.secondaryText}>Server date: {view.serverDate}</Text>
            <Text style={styles.secondaryText}>Worked out at: {view.computedAt}</Text>
            {outOfDate ? <Text style={styles.errorText} accessibilityRole="alert">{COPY.previewOutOfDate}</Text> : null}
            {!outOfDate && !inputsMatch ? <Text style={styles.helperText}>{COPY.previewInputsChanged}</Text> : null}

            <Text style={styles.statusText}>{view.outcome.label}</Text>
            {view.reason ? <Text style={styles.secondaryText}>{view.reason}</Text> : null}
            <Text style={styles.secondaryText}>{view.effect}</Text>
            {view.sourceNotice ? <Text style={styles.helperText}>{view.sourceNotice}</Text> : null}

            {view.rows.map((row) => (
              <View key={row.key} style={styles.targetRow}>
                <Text style={styles.label}>{row.goal}</Text>
                <Text style={styles.secondaryText}>Planned: {row.planned}</Text>
                <Text style={styles.secondaryText}>Would fit: {row.selected}</Text>
              </View>
            ))}
            <Text style={styles.secondaryText}>Planned in total: {view.planned}</Text>
            <Text style={styles.secondaryText}>Would fit in total: {view.selected}</Text>

            <Text style={styles.sectionTitle} accessibilityRole="header">Account</Text>
            {view.accountFigures.map((figure) => (
              <Text key={figure.label} style={styles.secondaryText}>{figure.label}: {figure.value}</Text>
            ))}

            {view.notices.map((notice) => (
              <Text key={notice} style={styles.helperText}>{notice}</Text>
            ))}
          </View>
        ) : null}

        {isAuto ? (
          <>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Turn on automatic rule"
              accessibilityState={{ disabled: !canTurnOn, busy: activating }}
              disabled={!canTurnOn}
              style={[styles.button, !canTurnOn && styles.disabledButton]}
              onPress={confirmTurnOn}
            >
              <Text style={styles.buttonText}>Turn on automatic rule</Text>
            </Pressable>
            {turnOnReason ? <Text style={styles.helperText}>{turnOnReason}</Text> : null}
          </>
        ) : null}
        {activating ? <ActivityIndicator style={styles.loader} accessibilityLabel="Turning the rule on" /> : null}

        {activationText ? (
          <Text
            style={activated ? styles.noticeText : styles.errorText}
            accessibilityRole="alert"
            accessibilityLiveRegion="polite"
          >
            {activationText}
          </Text>
        ) : null}
        {activated ? (
          <Pressable accessibilityRole="button" accessibilityLabel="Back to the rule" style={styles.button} onPress={() => router.back()}>
            <Text style={styles.buttonText}>Back to the rule</Text>
          </Pressable>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}
