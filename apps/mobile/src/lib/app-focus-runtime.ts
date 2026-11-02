// Binds installAppFocus to React Native's AppState and TanStack's focus manager.
// Called once from the root layout; the returned function removes the listener.
import { focusManager } from "@tanstack/react-query";
import { AppState, type AppStateStatus } from "react-native";

import { installAppFocus } from "./app-focus";

export const installAppFocusRuntime = (): (() => void) =>
  installAppFocus({
    focusManager,
    subscribeAppState: (listener) => {
      const subscription = AppState.addEventListener("change", (state: AppStateStatus) => listener(state));

      return () => subscription.remove();
    },
    getAppState: () => AppState.currentState,
  });
