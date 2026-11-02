import type { ReactNode } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import { QUERY_COPY, boundaryView, describeLoadFailure, loadingA11y, retryA11y } from "../lib/query-view";

// Loading, failure and empty presentations shared by the screens that read
// server data (VF-MOB-REFRESH-RETRY). They only DISPLAY: Retry re-runs the
// failed READ the screen passes in (a query's refetch), never a write. The text
// comes from describeLoadFailure, so no raw backend text reaches the user.

const styles = StyleSheet.create({
  block: { marginTop: 12 },
  message: { fontSize: 16 },
  hint: { fontSize: 13, marginTop: 4 },
  retry: {
    alignSelf: "flex-start",
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 10,
    paddingHorizontal: 16,
    marginTop: 8,
    minHeight: 44,
    justifyContent: "center",
  },
  retryText: { fontSize: 15, fontWeight: "600" },
  loader: { marginTop: 16 },
  empty: { fontSize: 16, marginTop: 8 },
});

// Retry for a dependent control whose own message the screen writes.
export function RetryAction({ what, retrying, onRetry }: { what: string; retrying: boolean; onRetry: () => void }) {
  return (
    <Pressable {...retryA11y(what, retrying)} disabled={retrying} style={styles.retry} onPress={onRetry}>
      {retrying ? <ActivityIndicator /> : <Text style={styles.retryText}>Retry</Text>}
    </Pressable>
  );
}

// The first load is in progress.
export function LoadingState({ what }: { what: string }) {
  return <ActivityIndicator style={styles.loader} {...loadingA11y(what)} />;
}

// The load failed and there is nothing to show: never rendered as "empty".
export function LoadError({
  what,
  error,
  onRetry,
  retrying,
}: {
  what: string;
  error: unknown;
  onRetry: () => void;
  retrying: boolean;
}) {
  const failure = describeLoadFailure(error, QUERY_COPY.loadFailed(what));

  return (
    <View style={styles.block} accessibilityRole="alert" accessibilityLiveRegion="polite">
      <Text style={styles.message}>{failure.message}</Text>
      <RetryAction what={what} retrying={retrying} onRetry={onRetry} />
    </View>
  );
}

// A refresh or a secondary read failed while valid data is still shown.
export function InlineError({
  what,
  error,
  kind,
  onRetry,
  retrying,
}: {
  what: string;
  error: unknown;
  kind: "refresh" | "partial";
  onRetry: () => void;
  retrying: boolean;
}) {
  const lead = kind === "refresh" ? QUERY_COPY.refreshFailed(what) : QUERY_COPY.partialFailed(what);
  const failure = describeLoadFailure(error, lead);

  return (
    <View style={styles.block} accessibilityRole="alert" accessibilityLiveRegion="polite">
      <Text style={styles.message}>{lead}</Text>
      {failure.message !== lead ? <Text style={styles.hint}>{failure.message}</Text> : null}
      <RetryAction what={what} retrying={retrying} onRetry={onRetry} />
    </View>
  );
}

export function EmptyState({ message }: { message: string }) {
  return <Text style={styles.empty}>{message}</Text>;
}

type BoundaryQuery<T> = {
  data: T | undefined;
  error: unknown;
  isError: boolean;
  isFetching: boolean;
  refetch: () => Promise<unknown>;
};

// One query rendered the same way everywhere: loading, failure with Retry (never
// an empty list), a failed refresh reported above the data that is still shown,
// the empty message, then the content. `isEmpty` and `empty` default to "an
// array with no items" and "No <what> yet.".
export function QueryBoundary<T>({
  query,
  what,
  isEmpty,
  empty,
  children,
}: {
  query: BoundaryQuery<T>;
  what: string;
  isEmpty?: (data: T) => boolean;
  empty?: string;
  children: (data: T) => ReactNode;
}) {
  const view = boundaryView(query, isEmpty ?? ((data) => Array.isArray(data) && data.length === 0));

  if (view.kind === "loading") {
    return <LoadingState what={what} />;
  }

  if (view.kind === "error" || query.data === undefined) {
    return <LoadError what={what} error={query.error} retrying={query.isFetching} onRetry={() => void query.refetch()} />;
  }

  const data = query.data;

  return (
    <>
      {view.refreshError ? (
        <InlineError
          what={what}
          error={query.error}
          kind="refresh"
          retrying={query.isFetching}
          onRetry={() => void query.refetch()}
        />
      ) : null}
      {view.kind === "empty" ? <EmptyState message={empty ?? QUERY_COPY.empty(what)} /> : children(data)}
    </>
  );
}
