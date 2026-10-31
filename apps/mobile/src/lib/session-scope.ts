import { QueryClientProvider } from "@tanstack/react-query";
import { createElement, useSyncExternalStore, type ReactElement, type ReactNode } from "react";

import type { SessionQueryClient } from "./session-query-client.ts";

// The authenticated part of the app, bound to ONE user session's QueryClient.
//
// TanStack's hooks create their QueryObserver / MutationObserver once per
// component instance and do not rebind when the provider's `client` prop
// changes. Keying the provider by the client generation makes React unmount the
// whole subtree and mount fresh components (new observers) whenever the
// signed-in user changes, so user A's observers are never reused for user B and
// A -> B -> A is a new logical session. A token refresh does not rotate, so it
// does not remount. The AuthProvider stays OUTSIDE this scope and is stable.
//
// Written without JSX so it can be exercised by the Node test runner.
export function SessionScope(props: {
  holder: SessionQueryClient;
  children?: ReactNode;
}): ReactElement {
  const { client, generation } = useSyncExternalStore(
    props.holder.subscribe,
    props.holder.getSnapshot,
  );

  return createElement(QueryClientProvider, { key: generation, client }, props.children);
}
