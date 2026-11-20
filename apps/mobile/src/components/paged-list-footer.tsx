import { ActivityIndicator, Pressable, Text, View, type StyleProp, type TextStyle, type ViewStyle } from "react-native";

import { PAGED_COPY, type MergedList, type PagedState } from "../lib/paged-list";
import { getUserFacingErrorMessage } from "../api/user-facing-error";

// The footer of a paged list (VF-MVP-BETA-001): "Load more", the loading
// spinner, a failed-page notice with Retry, or the end of the list. It only
// DISPLAYS: Load more and Retry call the screen's fetchNextPage, a read. The
// loaded rows above it are never touched. The wording of a failure comes from
// getUserFacingErrorMessage, never the raw backend text.
export function PagedListFooter({
  state,
  merged,
  what,
  error,
  onLoadMore,
  buttonStyle,
  buttonTextStyle,
  noteStyle,
}: {
  state: PagedState;
  merged: MergedList<unknown> | null;
  what: string;
  error: unknown;
  onLoadMore: () => void;
  buttonStyle: StyleProp<ViewStyle>;
  buttonTextStyle: StyleProp<TextStyle>;
  noteStyle: StyleProp<TextStyle>;
}) {
  if (merged === null || state.phase !== "list") {
    return null;
  }

  return (
    <View>
      <Text style={noteStyle}>{PAGED_COPY.shown(merged.items.length, merged.total)}</Text>

      {state.footer === "load_more" ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={PAGED_COPY.loadMoreLabel(merged.items.length, merged.total, what)}
          style={buttonStyle}
          onPress={onLoadMore}
        >
          <Text style={buttonTextStyle}>{PAGED_COPY.loadMore}</Text>
        </Pressable>
      ) : null}

      {state.footer === "loading_more" ? (
        <ActivityIndicator accessibilityLabel={PAGED_COPY.loadingMore(what)} />
      ) : null}

      {state.footer === "next_page_error" ? (
        <View accessibilityRole="alert" accessibilityLiveRegion="polite">
          <Text style={noteStyle}>{PAGED_COPY.nextPageFailed(what)}</Text>
          <Text style={noteStyle}>{getUserFacingErrorMessage(error, "Please try again.")}</Text>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={PAGED_COPY.retryMore(what)}
            style={buttonStyle}
            onPress={onLoadMore}
          >
            <Text style={buttonTextStyle}>Retry</Text>
          </Pressable>
        </View>
      ) : null}

      {state.footer === "stalled" ? <Text style={noteStyle}>{PAGED_COPY.stalled(what)}</Text> : null}
      {state.footer === "end" ? <Text style={noteStyle}>{PAGED_COPY.end(what)}</Text> : null}
    </View>
  );
}
