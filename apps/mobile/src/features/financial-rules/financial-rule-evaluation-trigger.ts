// Bounded, debounced trigger for POST /financial-rules/evaluate (VF-020F1).
//
// Evaluation drains the caller's own due income events; it is idempotent on
// the server but still a write, so the client keeps it deliberately rare:
//  * one trigger instance belongs to ONE signed-in user (and one QueryClient
//    generation); a signed-out or stale instance never sends a request;
//  * requests inside the debounce window collapse into one;
//  * never two evaluations at once: a request during a run is dropped, except
//    "income_recorded", which earns exactly ONE trailing run after the current
//    one (the new income may have arrived after the drain read its queue);
//  * "foreground" and "inbox_open" also respect a cooldown after the last run
//    STARTED, so rapid app switching cannot hammer the endpoint;
//  * a failure is reported and swallowed: there is no retry and no loop. The
//    POST is never repeated automatically; the next user-driven trigger is the
//    only way to run again;
//  * a result that arrives after dispose() or after the session changed is
//    discarded and updates nothing.
import type { QueryClient } from "@tanstack/react-query";

import { applyRuleInvalidation } from "./financial-rule-invalidation.ts";
import type { RuleEvaluationResult } from "./financial-rule.types.ts";

export type EvaluationReason = "foreground" | "inbox_open" | "income_recorded";

export type TriggerOutcome =
  | "scheduled"
  | "coalesced"
  | "ignored_signed_out"
  | "ignored_cooldown"
  | "disposed";

export const DEFAULT_DEBOUNCE_MS = 750;
export const DEFAULT_COOLDOWN_MS = 30_000;

export type CancelTimer = () => void;

export type EvaluationTriggerDeps = {
  // Null while signed out: the trigger then ignores everything.
  userId: string | null;
  // False once this user's session or QueryClient is gone.
  isCurrent: () => boolean;
  evaluate: (signal: AbortSignal) => Promise<RuleEvaluationResult>;
  // Called only with a result that still belongs to the current session.
  onResult: (result: RuleEvaluationResult, userId: string) => void | Promise<void>;
  onError?: (error: unknown) => void;
  debounceMs?: number;
  cooldownMs?: number;
  now?: () => number;
  setTimer?: (callback: () => void, ms: number) => CancelTimer;
};

export type EvaluationTrigger = {
  request: (reason: EvaluationReason) => TriggerOutcome;
  dispose: () => void;
  getState: () => { running: boolean; scheduled: boolean; trailing: boolean; disposed: boolean };
};

const defaultSetTimer = (callback: () => void, ms: number): CancelTimer => {
  const handle = setTimeout(callback, ms);

  return () => clearTimeout(handle);
};

export function createEvaluationTrigger(deps: EvaluationTriggerDeps): EvaluationTrigger {
  const debounceMs = deps.debounceMs ?? DEFAULT_DEBOUNCE_MS;
  const cooldownMs = deps.cooldownMs ?? DEFAULT_COOLDOWN_MS;
  const now = deps.now ?? Date.now;
  const setTimer = deps.setTimer ?? defaultSetTimer;

  let disposed = false;
  let running = false;
  let trailing = false;
  let cancelTimer: CancelTimer | null = null;
  let lastStartedAt: number | null = null;
  let controller: AbortController | null = null;

  const owns = (): boolean => !disposed && deps.userId !== null && deps.isCurrent();

  function schedule(): void {
    cancelTimer = setTimer(() => {
      cancelTimer = null;
      void run();
    }, debounceMs);
  }

  async function run(): Promise<void> {
    const userId = deps.userId;

    if (running || userId === null || !owns()) {
      return;
    }

    running = true;
    lastStartedAt = now();
    controller = new AbortController();

    try {
      const result = await deps.evaluate(controller.signal);

      // The session may have ended while the request was in flight.
      if (owns()) {
        await deps.onResult(result, userId);
      }
    } catch (error) {
      if (owns()) {
        deps.onError?.(error);
      }
    } finally {
      running = false;
      controller = null;

      if (trailing && owns()) {
        trailing = false;
        schedule();
      } else {
        trailing = false;
      }
    }
  }

  return {
    request(reason) {
      if (disposed) {
        return "disposed";
      }

      if (!owns()) {
        return "ignored_signed_out";
      }

      if (running) {
        // Only new income can make the run in flight incomplete.
        if (reason === "income_recorded") {
          trailing = true;
        }

        return "coalesced";
      }

      if (cancelTimer !== null) {
        return "coalesced";
      }

      if (
        reason !== "income_recorded" &&
        lastStartedAt !== null &&
        now() - lastStartedAt < cooldownMs
      ) {
        return "ignored_cooldown";
      }

      schedule();

      return "scheduled";
    },

    dispose() {
      disposed = true;
      trailing = false;
      cancelTimer?.();
      cancelTimer = null;
      controller?.abort();
    },

    getState: () => ({ running, scheduled: cancelTimer !== null, trailing, disposed }),
  };
}

export type RulesEvaluationDeps = {
  userId: string | null;
  queryClient: QueryClient;
  // True while `queryClient` is the live client of the signed-in user.
  isCurrent: () => boolean;
  evaluate: (signal: AbortSignal) => Promise<RuleEvaluationResult>;
  onError?: (error: unknown) => void;
  debounceMs?: number;
  cooldownMs?: number;
  now?: () => number;
  setTimer?: (callback: () => void, ms: number) => CancelTimer;
};

// The trigger wired to the cache: a current result invalidates exactly the
// "evaluated" set for this user (financial-rule-invalidation.ts).
export function createRulesEvaluationTrigger(deps: RulesEvaluationDeps): EvaluationTrigger {
  return createEvaluationTrigger({
    ...deps,
    onResult: async (result, userId) => {
      await applyRuleInvalidation(deps.queryClient, userId, { type: "evaluated", result });
    },
  });
}

// App-state transitions: fires "foreground" only when the app BECOMES active
// from a non-active state. The first evaluation after sign-in is requested by
// the session owner, not by this watcher.
export function watchForeground(
  subscribe: (listener: (state: string) => void) => () => void,
  trigger: Pick<EvaluationTrigger, "request">,
  initialState = "active",
): () => void {
  let previous = initialState;

  return subscribe((state) => {
    if (state === "active" && previous !== "active") {
      trigger.request("foreground");
    }

    previous = state;
  });
}
