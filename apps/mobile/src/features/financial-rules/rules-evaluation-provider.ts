// The ONE evaluation host of a signed-in session (VF-020F4). Written without
// JSX and without React Native / Supabase imports so the Node runner can mount
// it; rules-evaluation-host.tsx binds it to auth, AppState and the service.
//
// Lifetime: it sits inside SessionScope, which remounts its subtree whenever
// the QueryClient rotates (user change or sign-out). The effect below therefore
// creates exactly one trigger and one app-state subscription per session /
// client generation, and its cleanup disposes both. Nothing else in the app
// listens to AppState for rules or calls evaluate.
import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";
import type { QueryClient } from "@tanstack/react-query";

import {
  createRulesEvaluationTrigger,
  watchForeground,
  type EvaluationReason,
  type EvaluationStatus,
  type EvaluationTrigger,
  type TriggerOutcome,
} from "./financial-rule-evaluation-trigger.ts";
import type { RuleEvaluationResult } from "./financial-rule.types.ts";

export type RulesEvaluationContextValue = {
  // Asks for an evaluation (debounced, cooldown-limited). Safe to call anywhere.
  request: (reason: EvaluationReason) => TriggerOutcome;
  // The last attempt in THIS session; "not_attempted" before the first one.
  status: EvaluationStatus;
};

const NOT_AVAILABLE: RulesEvaluationContextValue = {
  request: () => "ignored_signed_out",
  status: "not_attempted",
};

const RulesEvaluationContext = createContext<RulesEvaluationContextValue>(NOT_AVAILABLE);

export const useRulesEvaluation = (): RulesEvaluationContextValue => useContext(RulesEvaluationContext);

function createTriggerHandle() {
  let current: EvaluationTrigger | null = null;

  return {
    attach(trigger: EvaluationTrigger | null): void {
      current = trigger;
    },
    request(reason: EvaluationReason): TriggerOutcome {
      return current?.request(reason) ?? "ignored_signed_out";
    },
  };
}

export type RulesEvaluationProviderProps = {
  // Null while signed out: no trigger exists.
  userId: string | null;
  isCurrentClient: (client: QueryClient) => boolean;
  evaluate: (signal: AbortSignal) => Promise<RuleEvaluationResult>;
  subscribeAppState: (listener: (state: string) => void) => () => void;
  getAppState: () => string;
  onError?: (error: unknown) => void;
  // Test seam; production uses the F1 defaults (750 ms debounce, 30 s cooldown).
  timing?: { debounceMs?: number; cooldownMs?: number };
  children?: ReactNode;
};

export function RulesEvaluationProvider(props: RulesEvaluationProviderProps): ReactElement {
  const { userId, isCurrentClient, evaluate, subscribeAppState, getAppState, onError, timing } = props;
  const client = useQueryClient();
  // A stable handle for the live trigger (attached and detached only by the
  // effect below).
  const [handle] = useState(createTriggerHandle);
  // The status belongs to the user it was recorded for, so a value from a
  // previous session can never be read by the next one.
  const [recorded, setRecorded] = useState<{ userId: string; status: EvaluationStatus } | null>(null);

  useEffect(() => {
    if (userId === null) {
      return undefined;
    }

    const trigger = createRulesEvaluationTrigger({
      userId,
      queryClient: client,
      isCurrent: () => isCurrentClient(client),
      evaluate,
      onError,
      onStatus: (status) => setRecorded({ userId, status }),
      debounceMs: timing?.debounceMs,
      cooldownMs: timing?.cooldownMs,
    });
    const stopForeground = watchForeground(subscribeAppState, trigger, getAppState());

    handle.attach(trigger);
    // The session is ready.
    trigger.request("foreground");

    return () => {
      stopForeground();
      trigger.dispose();
      handle.attach(null);
    };
  }, [handle, userId, client, isCurrentClient, evaluate, subscribeAppState, getAppState, onError, timing?.debounceMs, timing?.cooldownMs]);

  const request = useCallback(
    (reason: EvaluationReason): TriggerOutcome => handle.request(reason),
    [handle],
  );
  const status: EvaluationStatus = recorded !== null && recorded.userId === userId ? recorded.status : "not_attempted";
  const value = useMemo(() => ({ request, status }), [request, status]);

  return createElement(RulesEvaluationContext.Provider, { value }, props.children);
}
