// User-facing wording of the Smart Rules feature (VF-020F1). Plain language,
// no technical detail, and bound by the decision-record copy rules:
//  C1  rules are checked when the app opens or refreshes and after income is
//      recorded - never "while the app is closed";
//  C2  a reservation is an earmark inside an Account, never a transfer;
//  C3  "available to reserve", never "safe to spend" or a total balance;
//  C7  no count and no "unread" for the Inbox;
//  C8  a preview is a hypothetical example, never a promise.
// financial-rule-forbidden-copy.test.ts scans this directory.

export const COPY = {
  // C1
  checkedWhen: "Rules are checked when you open or refresh the app and after you record income.",
  // C2
  reservationMeaning:
    "A reservation sets money aside inside an Account for a Goal. It does not move any money in your bank.",
  // C3
  reservableLabel: "Available to reserve",
  ruleCapacityLabel: "Available to this rule",
  floorLabel: "Minimum unallocated amount",
  holdsLabel: "Held for pending suggestions",
  // C8
  previewLabel: "Example only",
  previewDisclaimer:
    "This is an example worked out from your current figures and a sample income. Nothing was recorded or reserved, and a real income may turn out differently.",
  previewIncomeNotRecorded: "The sample income is not recorded anywhere.",
  previewEligibilityNotSimulated:
    "Whether a real future income qualifies for this rule is not checked here.",
  previewOtherRulesNotSimulated: "Your other rules are not included in this example.",
  previewRuleNotEnabled: "This rule is not turned on, so it would not run for a real income.",
  previewWouldApply: "If this rule were on and an income like this arrived, this much would be reserved right away.",
  previewWouldHold:
    "If an income like this arrived, a suggestion would be made and held for you to confirm. Nothing is reserved until you confirm.",
  // Alerts degrade when the alerts feature is not set up in this environment.
  alertsUnavailable: "Alerts are not available yet.",
  evaluationBlocked: "Some income is still waiting to be checked. Try again in a moment.",
  evaluationAlertsFailed: "Alerts could not be refreshed just now.",
  fallbackReason: "No further detail is available for this outcome.",
  // After a POST whose answer never arrived the effect is unknown.
  outcomeUnknown:
    "We could not confirm whether this went through. Check the list before trying again.",
} as const;

export const MODE_COPY = {
  AUTO: {
    label: "Automatic",
    description: `Reserves the money by itself when the rule runs. ${COPY.checkedWhen}`,
  },
  CONFIRM: {
    label: "Ask me first",
    description: "Suggests reservations and waits for you to confirm them. Nothing is reserved until you do.",
  },
} as const;

export const POLICY_COPY = {
  FIXED_PER_GOAL: { label: "Fixed amount per Goal" },
  PERCENT_OF_INCOME_WATERFALL: { label: "Percent of income, in Goal priority order" },
} as const;

export const RULE_TYPE_COPY = {
  INCOME_ALLOCATION: { label: "Reserve from income" },
  MINIMUM_UNALLOCATED_FLOOR: { label: "Minimum unallocated amount" },
  OVERCOMMITMENT_ALERT: { label: "Overcommitment alert" },
  BUDGET_ALERT: { label: "Budget alert" },
} as const;

export const SOURCE_COPY = {
  salary: "Salary",
  freelance: "Freelance",
  refund: "Refund",
  gift: "Gift",
  other: "Other",
} as const;
