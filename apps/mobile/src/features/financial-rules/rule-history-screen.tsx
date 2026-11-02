import { useMemo, useState } from "react";
import { useLocalSearchParams } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  SafeAreaView,
  ScrollView,
  Text,
  View,
} from "react-native";

import { useAuth } from "../auth/auth-context";
import { getGoals } from "../goals/goal.service";
import {
  NO_HISTORY_FILTERS,
  deriveHistoryState,
  isFiltered,
  parseRuleParam,
  type HistoryFilters,
} from "./execution-history-data";
import {
  HISTORY_COPY,
  buildHistoryCard,
  checkNotice,
  type NameDirectory,
} from "./execution-history-view";
import { describeRuleError } from "./financial-rule-errors";
import { financialRuleKeys } from "./financial-rule-query-keys";
import { executionStatusInfo } from "./financial-rule-presentation";
import { financialRulesService } from "./financial-rule.service";
import { EXECUTION_STATUSES } from "./financial-rule.types";
import { OptionPicker, type PickerOption } from "./option-picker";
import { RuleHistoryCard } from "./rule-history-card";
import { useRulesEvaluation } from "./rules-evaluation-provider";
import { styles } from "./rules.styles";
import { useExecutionHistory } from "./use-execution-history";

const SIGNED_OUT = ["financial-rules", "signed-out"] as const;
const ALL_RULES = "all";

function directory(items: { id: string; name: string }[] | undefined): NameDirectory {
  return { loaded: items !== undefined, names: new Map((items ?? []).map((item) => [item.id, item.name])) };
}

// R-11: every recorded run of the user's rules, newest first. Read-only: it
// reads the evaluation status for one line of context and never asks for an
// evaluation, and it calls no mutation. Names are looked up from the Rules and
// Goals the app already holds and are shown as current names.
export function RuleHistoryScreen() {
  const params = useLocalSearchParams<{ rule_id?: string | string[] }>();
  const parsed = useMemo(() => parseRuleParam(params.rule_id), [params.rule_id]);
  const { session } = useAuth();
  const userId = session?.user.id ?? null;
  const [filters, setFilters] = useState<HistoryFilters>({ ruleId: parsed.ruleId, status: null });
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const { status: checkStatus } = useRulesEvaluation();

  const { feed, merged } = useExecutionHistory({
    userId,
    filters,
    listExecutions: (requestFilters, signal) => financialRulesService.listExecutions(requestFilters, signal),
  });
  const rulesQuery = useQuery({
    queryKey: userId ? financialRuleKeys.ruleList(userId) : SIGNED_OUT,
    queryFn: ({ signal }) => financialRulesService.listRules(signal),
    enabled: userId !== null,
  });
  const goalsQuery = useQuery({ queryKey: ["goals", userId], queryFn: getGoals, enabled: userId !== null });

  const rules = useMemo(() => directory(rulesQuery.data), [rulesQuery.data]);
  const goals = useMemo(() => directory(goalsQuery.data), [goalsQuery.data]);

  const ruleOptions: PickerOption[] = useMemo(() => {
    const allocation = (rulesQuery.data ?? []).filter((rule) => rule.rule_type === "INCOME_ALLOCATION");
    const options: PickerOption[] = [
      { id: ALL_RULES, label: HISTORY_COPY.allRules },
      ...allocation.map((rule) => ({ id: rule.id, label: rule.name })),
    ];

    // A rule from a link that is not in the loaded list is still selectable text.
    if (filters.ruleId !== null && !options.some((option) => option.id === filters.ruleId)) {
      options.push({ id: filters.ruleId, label: rules.loaded ? HISTORY_COPY.ruleGone : HISTORY_COPY.ruleFallback });
    }

    return options;
  }, [rulesQuery.data, filters.ruleId, rules.loaded]);

  const state = deriveHistoryState({
    signedIn: userId !== null,
    hasData: merged !== null,
    itemCount: merged?.items.length ?? 0,
    isError: feed.isError,
    isFetchNextPageError: feed.isFetchNextPageError,
    isFetchingNextPage: feed.isFetchingNextPage,
    hasMore: merged?.hasMore ?? false,
    stalled: merged?.stalled ?? false,
    filtered: isFiltered(filters),
  });
  const notice = checkNotice(checkStatus);
  const errorMessage = feed.isError ? describeRuleError(feed.error, "Could not load your history.").message : null;

  function toggle(id: string) {
    setOpen((current) => {
      const next = new Set(current);

      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }

      return next;
    });
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl
            refreshing={feed.isRefetching && !feed.isFetchingNextPage}
            onRefresh={() => void feed.refetch()}
          />
        }
      >
        <Text style={styles.title} accessibilityRole="header">{HISTORY_COPY.title}</Text>
        <Text style={styles.helperText}>{HISTORY_COPY.intro}</Text>
        {parsed.invalid ? <Text style={styles.noticeText}>{HISTORY_COPY.invalidRuleLink}</Text> : null}
        {notice ? <Text style={styles.noticeText} accessibilityLiveRegion="polite">{notice}</Text> : null}

        <View style={styles.formGroup}>
          <Text style={styles.label} accessibilityRole="header">{HISTORY_COPY.ruleFilterTitle}</Text>
          <OptionPicker
            title={HISTORY_COPY.ruleFilterTitle}
            placeholder={HISTORY_COPY.allRules}
            options={ruleOptions}
            selectedId={filters.ruleId ?? ALL_RULES}
            onChange={(id) => setFilters((current) => ({ ...current, ruleId: id === ALL_RULES ? null : id }))}
          />
        </View>

        <View style={styles.formGroup}>
          <Text style={styles.label} accessibilityRole="header">{HISTORY_COPY.statusFilterTitle}</Text>
          <View style={styles.chipRow}>
            {[null, ...EXECUTION_STATUSES].map((option) => {
              const selected = filters.status === option;
              const label = option === null ? HISTORY_COPY.allStatuses : executionStatusInfo(option).label;

              return (
                <Pressable
                  key={option ?? "all"}
                  accessibilityRole="radio"
                  accessibilityState={{ checked: selected }}
                  accessibilityLabel={label}
                  style={[styles.chip, selected && styles.chipSelected]}
                  onPress={() => setFilters((current) => ({ ...current, status: option }))}
                >
                  <Text style={[styles.chipText, selected && styles.chipTextSelected]}>
                    {selected ? `✓ ${label}` : label}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </View>

        {state.phase === "signed_out" ? <Text style={styles.secondaryText}>{HISTORY_COPY.signedOut}</Text> : null}
        {state.phase === "loading" ? (
          <ActivityIndicator style={styles.loader} accessibilityLabel={HISTORY_COPY.loading} />
        ) : null}

        {state.phase === "error" ? (
          <>
            <Text style={styles.errorText} accessibilityRole="alert" accessibilityLiveRegion="polite">{errorMessage}</Text>
            <Pressable accessibilityRole="button" accessibilityLabel="Retry" style={styles.button} onPress={() => void feed.refetch()}>
              <Text style={styles.buttonText}>Retry</Text>
            </Pressable>
          </>
        ) : null}

        {state.refreshError ? (
          <>
            <Text style={styles.errorText} accessibilityRole="alert" accessibilityLiveRegion="polite">{errorMessage}</Text>
            <Pressable accessibilityRole="button" accessibilityLabel="Retry refresh" style={styles.button} onPress={() => void feed.refetch()}>
              <Text style={styles.buttonText}>Retry</Text>
            </Pressable>
          </>
        ) : null}

        {state.phase === "empty" ? <Text style={styles.secondaryText}>{HISTORY_COPY.empty}</Text> : null}
        {state.phase === "empty_filtered" ? (
          <>
            <Text style={styles.secondaryText}>{HISTORY_COPY.emptyFiltered}</Text>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={HISTORY_COPY.clearFilters}
              style={styles.editButton}
              onPress={() => setFilters(NO_HISTORY_FILTERS)}
            >
              <Text style={styles.editButtonText}>{HISTORY_COPY.clearFilters}</Text>
            </Pressable>
          </>
        ) : null}

        {state.phase === "list" && merged ? (
          <>
            <Text style={styles.helperText} accessibilityLabel={`Showing ${merged.items.length} of ${merged.total}`}>
              Showing {merged.items.length} of {merged.total}
            </Text>
            {merged.items.map((execution) => (
              <RuleHistoryCard
                key={execution.id}
                view={buildHistoryCard(execution, rules, goals)}
                expanded={open.has(execution.id)}
                onToggle={() => toggle(execution.id)}
              />
            ))}
          </>
        ) : null}

        {state.footer === "load_more" && merged ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`Load more, showing ${merged.items.length} of ${merged.total}`}
            style={styles.button}
            onPress={() => void feed.fetchNextPage()}
          >
            <Text style={styles.buttonText}>Load more</Text>
          </Pressable>
        ) : null}
        {state.footer === "loading_more" ? (
          <ActivityIndicator style={styles.loader} accessibilityLabel="Loading more history" />
        ) : null}
        {state.footer === "next_page_error" ? (
          <>
            <Text style={styles.errorText} accessibilityRole="alert" accessibilityLiveRegion="polite">{errorMessage}</Text>
            <Pressable accessibilityRole="button" accessibilityLabel="Retry loading more" style={styles.button} onPress={() => void feed.fetchNextPage()}>
              <Text style={styles.buttonText}>Retry</Text>
            </Pressable>
          </>
        ) : null}
        {state.footer === "stalled" ? <Text style={styles.noticeText}>{HISTORY_COPY.stalled}</Text> : null}
        {state.footer === "end" ? <Text style={styles.secondaryText}>{HISTORY_COPY.end}</Text> : null}
        {state.phase === "list" ? <Text style={styles.helperText}>{HISTORY_COPY.paging}</Text> : null}
      </ScrollView>
    </SafeAreaView>
  );
}
