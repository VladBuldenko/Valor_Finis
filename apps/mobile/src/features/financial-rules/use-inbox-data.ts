// The shared Inbox data (VF-020F4): three independent queries, the evaluation
// status and the ONE derived indicator. The Dashboard button and the Inbox
// screen both call this hook, so they read the same cached query data.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { useAuth } from "../auth/auth-context";
import {
  INBOX_MAX_PAGES,
  INBOX_PAGE_SIZE,
  RECENT_EXECUTIONS_LIMIT,
  deriveInboxIndicator,
  fetchBoundedPages,
  sourceStateFromQuery,
  type BoundedPages,
} from "./inbox-data";
import { financialRuleKeys } from "./financial-rule-query-keys";
import { financialRulesService } from "./financial-rule.service";
import type { RuleAlert, RuleExecution, RuleProposal } from "./financial-rule.types";
import { useRulesEvaluation } from "./rules-evaluation-provider";

// A clock for expiry checks: read once, then refreshed every minute, so render
// stays pure and an open suggestion stops counting as actionable on time.
function useNow(intervalMs = 60_000): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);

    return () => clearInterval(timer);
  }, [intervalMs]);

  return now;
}

const SIGNED_OUT = ["financial-rules", "signed-out"] as const;

export function useInboxData() {
  const { session } = useAuth();
  const userId = session?.user.id;
  const enabled = Boolean(userId);
  const evaluation = useRulesEvaluation();
  const now = useNow();

  const proposals = useQuery<BoundedPages<RuleProposal>>({
    queryKey: userId ? financialRuleKeys.inboxProposals(userId) : SIGNED_OUT,
    queryFn: () =>
      fetchBoundedPages(
        (offset) =>
          financialRulesService.listProposals({ status: "awaiting_confirmation", limit: INBOX_PAGE_SIZE, offset }),
        INBOX_MAX_PAGES,
      ),
    enabled,
  });
  const alerts = useQuery<BoundedPages<RuleAlert>>({
    queryKey: userId ? financialRuleKeys.inboxAlerts(userId) : SIGNED_OUT,
    queryFn: () =>
      fetchBoundedPages(
        (offset) => financialRulesService.listAlerts({ acknowledged: false, limit: INBOX_PAGE_SIZE, offset }),
        INBOX_MAX_PAGES,
      ),
    enabled,
  });
  // Informational only: never part of the indicator.
  const executions = useQuery({
    queryKey: userId ? financialRuleKeys.inboxExecutions(userId) : SIGNED_OUT,
    queryFn: () => financialRulesService.listExecutions({ limit: RECENT_EXECUTIONS_LIMIT }),
    enabled,
  });

  const indicator = deriveInboxIndicator({
    proposals: sourceStateFromQuery(proposals),
    alerts: sourceStateFromQuery(alerts),
    evaluation: evaluation.status,
    now,
  });

  return {
    proposals,
    alerts,
    executions: executions as typeof executions & { data: { items: RuleExecution[] } | undefined },
    evaluation,
    indicator,
  };
}
