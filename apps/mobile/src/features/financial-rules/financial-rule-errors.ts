// Maps a failed Smart Rules request to what the app shows and does
// (VF-020F1). The stable BE-1 `code` is read FIRST; only when it is absent or
// unknown does the mapping fall back to the shared status/kind messages of
// getUserFacingErrorMessage, which never expose a body, URL or stack trace.
import { isApiError } from "../../api/api-error.ts";
import { getUserFacingErrorMessage } from "../../api/user-facing-error.ts";
import { COPY } from "./financial-rule-copy.ts";

export type RuleErrorCategory =
  | "not_found"
  | "stale"
  | "conflict"
  | "invalid_transition"
  | "activation_unavailable"
  | "deletion_blocked"
  | "capacity"
  | "subject_archived"
  | "invalid_config"
  | "preview_unavailable"
  | "validation"
  | "auth"
  | "outcome_unknown"
  | "network"
  | "server"
  | "unknown";

type CodeEntry = { category: RuleErrorCategory; message: string };

const CODE_MAP = {
  financial_rule_not_found: { category: "not_found", message: "This rule no longer exists." },
  rule_proposal_not_found: { category: "not_found", message: "This suggestion no longer exists." },
  rule_alert_not_found: { category: "not_found", message: "This alert no longer exists." },
  rule_proposal_stale: {
    category: "stale",
    message: "This suggestion is out of date and was cancelled. Nothing was reserved.",
  },
  financial_rule_already_exists: {
    category: "conflict",
    message: "You already have a rule of this kind for this Account or Budget.",
  },
  financial_rule_invalid_transition: {
    category: "invalid_transition",
    message: "That change is not possible from the rule's current state. Refresh and try again.",
  },
  financial_rule_activation_not_available: {
    category: "activation_unavailable",
    message: "Alerts are not available yet in this environment, so this rule cannot be turned on.",
  },
  financial_rule_deletion_not_allowed: {
    category: "deletion_blocked",
    message: "This rule cannot be deleted. Turn it off instead.",
  },
  financial_rule_subject_archived: {
    category: "subject_archived",
    message: "The rule refers to an archived Account or Goal. Choose active ones.",
  },
  financial_rule_currency_mismatch: {
    category: "invalid_config",
    message: "The Account and every Goal in a rule must use the same currency.",
  },
  financial_rule_invalid_fields: {
    category: "invalid_config",
    message: "Some rule settings are not valid. Check them and try again.",
  },
  financial_rule_preview_not_available: {
    category: "preview_unavailable",
    message: "An example is only available for rules that reserve money from income.",
  },
  goal_reservation_capacity_exceeded: {
    category: "capacity",
    message: "There is not enough available to reserve. Nothing was reserved.",
  },
  account_archived: { category: "subject_archived", message: "This Account is archived." },
  goal_archived: { category: "subject_archived", message: "This Goal is archived." },
  validation_error: { category: "validation", message: "Check the values you entered and try again." },
  unauthorized: { category: "auth", message: "Your session has expired. Please sign in again." },
} as const satisfies Record<string, CodeEntry>;

export type KnownRuleErrorCode = keyof typeof CODE_MAP;

export const KNOWN_RULE_ERROR_CODES = Object.keys(CODE_MAP) as KnownRuleErrorCode[];

function isKnownCode(code: string): code is KnownRuleErrorCode {
  return Object.prototype.hasOwnProperty.call(CODE_MAP, code);
}

export type RuleErrorInfo = {
  category: RuleErrorCategory;
  message: string;
  // The BE-1 code when the server sent one (logging/tests); never shown.
  code: string | null;
  // A hint that trying again by hand is reasonable. Nothing retries by itself.
  retryable: boolean;
};

export type DescribeContext = {
  // True for a POST/PATCH/DELETE: a timeout or lost connection then leaves the
  // effect UNKNOWN, and the message must say so instead of "failed".
  mutation: boolean;
};

export function describeRuleError(
  error: unknown,
  fallback: string,
  context: DescribeContext = { mutation: false },
): RuleErrorInfo {
  if (!isApiError(error)) {
    return { category: "unknown", message: fallback, code: null, retryable: false };
  }

  // Every authentication code (auth_*) means "sign in again".
  if (error.code !== null && error.code.startsWith("auth_")) {
    return {
      category: "auth",
      message: CODE_MAP.unauthorized.message,
      code: error.code,
      retryable: false,
    };
  }

  if (error.code !== null && isKnownCode(error.code)) {
    const entry: CodeEntry = CODE_MAP[error.code];

    return { category: entry.category, message: entry.message, code: error.code, retryable: false };
  }

  switch (error.kind) {
    case "timeout":
    case "network":
      return context.mutation
        ? { category: "outcome_unknown", message: COPY.outcomeUnknown, code: error.code, retryable: false }
        : {
            category: "network",
            message: getUserFacingErrorMessage(error, fallback),
            code: error.code,
            retryable: true,
          };
    case "unauthorized":
    case "unauthenticated":
      return {
        category: "auth",
        message: getUserFacingErrorMessage(error, fallback),
        code: error.code,
        retryable: false,
      };
    case "cancelled":
      return {
        category: "unknown",
        message: getUserFacingErrorMessage(error, fallback),
        code: error.code,
        retryable: true,
      };
    case "malformed_response":
      // A 2xx whose body could not be read: for a mutation the write may have happened.
      return context.mutation
        ? { category: "outcome_unknown", message: COPY.outcomeUnknown, code: error.code, retryable: false }
        : {
            category: "server",
            message: getUserFacingErrorMessage(error, fallback),
            code: error.code,
            retryable: true,
          };
    case "http":
      return {
        category: error.status !== null && error.status >= 500 ? "server" : "unknown",
        message: getUserFacingErrorMessage(error, fallback),
        code: error.code,
        retryable: error.status !== null && error.status >= 500,
      };
    default: {
      const exhaustive: never = error.kind;

      return { category: "unknown", message: fallback, code: String(exhaustive), retryable: false };
    }
  }
}
