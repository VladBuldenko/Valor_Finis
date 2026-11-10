import { AppState, type AppStateStatus } from "react-native";
import type { ReactNode } from "react";

import { isCurrentQueryClient } from "../../lib/session-runtime";
import { useAppUserId } from "../auth/auth-context";
import { financialRulesService } from "./financial-rule.service";
import { RulesEvaluationProvider } from "./rules-evaluation-provider";

const evaluate = (signal: AbortSignal) => financialRulesService.evaluateRules(signal);

const subscribeAppState = (listener: (state: string) => void): (() => void) => {
  const subscription = AppState.addEventListener("change", (state: AppStateStatus) => listener(state));

  return () => subscription.remove();
};

const getAppState = (): string => AppState.currentState;

// Mounted once in the root layout, inside SessionScope (see the provider).
export function RulesEvaluationHost({ children }: { children: ReactNode }) {
  // Null while signed out or while a password recovery is in progress (the
  // recovery session must not drive data requests).
  const userId = useAppUserId();

  return (
    <RulesEvaluationProvider
      userId={userId}
      isCurrentClient={isCurrentQueryClient}
      evaluate={evaluate}
      subscribeAppState={subscribeAppState}
      getAppState={getAppState}
    >
      {children}
    </RulesEvaluationProvider>
  );
}
