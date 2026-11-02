// The execution-history query (VF-020F6): one infinite query per user and
// filter pair. Written without auth, Router or React Native imports so the
// Node runner can mount it under the real SessionScope; the screen binds it to
// the signed-in user and the service.
//
// Ownership: the key starts with the user id and the QueryClient is replaced
// when the user changes, so another user's pages can neither be read from nor
// written to this entry. Each page's offset is its pageParam, derived from the
// number of rows already RECEIVED. The queryFn forwards TanStack's AbortSignal.
// It only reads: no mutation, no evaluate.
import { useInfiniteQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import {
  HISTORY_PAGE_SIZE,
  historyKeyFilters,
  historyRequestFilters,
  mergeHistoryPages,
  nextHistoryOffset,
  receivedCount,
  type HistoryFilters,
  type MergedHistory,
} from "./execution-history-data.ts";
import { financialRuleKeys } from "./financial-rule-query-keys.ts";
import type { RuleExecutionFilters, RuleExecutionList } from "./financial-rule.types.ts";

export type ListExecutions = (filters: RuleExecutionFilters, signal?: AbortSignal) => Promise<RuleExecutionList>;

const SIGNED_OUT = ["financial-rules", "signed-out"] as const;

export function useExecutionHistory(args: {
  userId: string | null;
  filters: HistoryFilters;
  listExecutions: ListExecutions;
}) {
  const { userId, filters, listExecutions } = args;

  const feed = useInfiniteQuery({
    queryKey: userId === null ? SIGNED_OUT : financialRuleKeys.executionHistory(userId, historyKeyFilters(filters)),
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => listExecutions(historyRequestFilters(filters, pageParam), signal),
    getNextPageParam: (last: RuleExecutionList, pages: RuleExecutionList[]) =>
      nextHistoryOffset(last, receivedCount(pages)),
    enabled: userId !== null,
  });

  const merged: MergedHistory | null = useMemo(
    () => (feed.data === undefined ? null : mergeHistoryPages(feed.data.pages)),
    [feed.data],
  );

  return { feed, merged, pageSize: HISTORY_PAGE_SIZE };
}
