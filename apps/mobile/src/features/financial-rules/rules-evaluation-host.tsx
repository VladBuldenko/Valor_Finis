import { AppState, type AppStateStatus } from "react-native";
import type { ReactNode } from "react";

import { isCurrentQueryClient } from "../../lib/session-runtime";
import { useAuth } from "../auth/auth-context";
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
  const { session } = useAuth();

  return (
    <RulesEvaluationProvider
      userId={session?.user.id ?? null}
      isCurrentClient={isCurrentQueryClient}
      evaluate={evaluate}
      subscribeAppState={subscribeAppState}
      getAppState={getAppState}
    >
      {children}
    </RulesEvaluationProvider>
  );
}
