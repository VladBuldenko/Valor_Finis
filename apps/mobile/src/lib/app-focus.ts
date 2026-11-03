// The ONE bridge from the app's foreground state to TanStack Query's focus
// manager (VF-MOB-REFRESH-RETRY). Without it React Native never reports focus
// (there is no window.addEventListener), so nothing refetches when the user
// returns to the app.
//
// What it does: report `true` on a real inactive/background -> active change and
// `false` when the app leaves the foreground. A repeated identical state (a
// second "active", or "background" after "inactive") is dropped here, and the
// focus manager itself ignores a value it already holds. TanStack then refetches
// only ACTIVE (mounted) queries whose data is stale: no cache-wide invalidation.
// Foreground refetching is GET-only; the rules evaluation host keeps its own,
// separate AppState subscription for the debounced evaluate, and the auth client
// keeps its own for token auto-refresh. This module never calls the network.
export type FocusSink = { setFocused: (focused?: boolean) => void };

export type AppFocusDeps = {
  focusManager: FocusSink;
  // Returns the unsubscribe function.
  subscribeAppState: (listener: (state: string) => void) => () => void;
  getAppState: () => string;
};

export function installAppFocus(deps: AppFocusDeps): () => void {
  // What was last reported to the focus manager. The start state is the app's
  // current one and is NOT reported: starting must not look like a foreground.
  let focused = deps.getAppState() === "active";
  let installed = true;

  const unsubscribe = deps.subscribeAppState((state) => {
    if (!installed) {
      return;
    }

    const nowActive = state === "active";

    if (nowActive === focused) {
      return;
    }

    focused = nowActive;
    deps.focusManager.setFocused(nowActive);
  });

  return () => {
    installed = false;
    unsubscribe();
  };
}
