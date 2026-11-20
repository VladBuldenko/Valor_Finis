// A paged list query (VF-MVP-BETA-001): one infinite query per user and list,
// written without auth, Router or React Native imports so the Node runner can
// mount it. The screen binds it to the signed-in user and the service.
//
// Ownership: the caller's key starts with the user id and the QueryClient is
// replaced when the user changes, so another user's pages can neither be read
// from nor written to this entry. Each page's offset is its pageParam, derived
// from the number of rows already RECEIVED. The queryFn forwards TanStack's
// AbortSignal. It only reads: no mutation.
import { useInfiniteQuery, type QueryKey } from "@tanstack/react-query";
import { useMemo } from "react";

import { LIST_PAGE_SIZE, derivePagedState, mergePages, nextPageOffset, receivedCount, type MergedList, type Page, type PagedState } from "./paged-list.ts";

export type FetchPage<T> = (limit: number, offset: number, signal?: AbortSignal) => Promise<Page<T>>;

const SIGNED_OUT = ["paged-list", "signed-out"] as const;

export function usePagedList<T extends { id: string }>(args: {
  queryKey: QueryKey | null;
  fetchPage: FetchPage<T>;
  pageSize?: number;
}) {
  const { queryKey, fetchPage, pageSize = LIST_PAGE_SIZE } = args;

  const feed = useInfiniteQuery({
    queryKey: queryKey ?? SIGNED_OUT,
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => fetchPage(pageSize, pageParam, signal),
    getNextPageParam: (last: Page<T>, pages: Page<T>[]) => nextPageOffset(last, receivedCount(pages)),
    enabled: queryKey !== null,
  });

  const merged: MergedList<T> | null = useMemo(
    () => (feed.data === undefined ? null : mergePages(feed.data.pages)),
    [feed.data],
  );

  const state: PagedState = derivePagedState({
    hasData: merged !== null,
    itemCount: merged?.items.length ?? 0,
    isError: feed.isError,
    isFetchNextPageError: feed.isFetchNextPageError,
    isFetchingNextPage: feed.isFetchingNextPage,
    hasMore: merged?.hasMore ?? false,
    stalled: merged?.stalled ?? false,
  });

  return { feed, merged, state, pageSize };
}
