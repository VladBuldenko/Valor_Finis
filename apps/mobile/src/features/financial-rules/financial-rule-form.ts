// Form state, shape validation and request building for the four rule
// editors (VF-020F3). Pure and Node-testable.
//
// Validation here is SHAPE-ONLY convenience (required, decimal format, bounds
// the backend also enforces); the backend stays authoritative and its stable
// error code is mapped by describeRuleError. Nothing here plans, simulates or
// computes money: amounts stay strings and are only compared as text.
import {
  DEFAULT_INCOME_SOURCES,
  INCOME_SOURCES,
  MAX_TARGETS_PER_RULE,
  type ExecutionMode,
  type FinancialRule,
  type FinancialRuleCreate,
  type FinancialRuleUpdate,
  type IncomeAllocationRule,
  type IncomeSource,
  type RulePolicy,
  type RuleStatus,
  type RuleType,
  assertNever,
} from "./financial-rule.types.ts";
import { isMaterialRuleEdit } from "./financial-rule-presentation.ts";

export const MAX_NAME_LENGTH = 150;
export const MAX_DESCRIPTION_LENGTH = 255;

export type TargetFormRow = {
  goalId: string;
  // Fixed amount (FIXED_PER_GOAL) or optional cap (percent policy); "" = none.
  amount: string;
};

type FormBase = { name: string; description: string };

export type AllocationFormState = FormBase & {
  ruleType: "INCOME_ALLOCATION";
  sourceAccountId: string | null;
  executionMode: ExecutionMode;
  policy: RulePolicy;
  percent: string;
  targets: TargetFormRow[];
  incomeSources: IncomeSource[];
  capAtTarget: boolean;
  allowPartial: boolean;
  // "" = let the server use the date of the first turn-on.
  effectiveFrom: string;
};

export type FloorFormState = FormBase & {
  ruleType: "MINIMUM_UNALLOCATED_FLOOR";
  sourceAccountId: string | null;
  floorAmount: string;
};

export type OvercommitmentFormState = FormBase & {
  ruleType: "OVERCOMMITMENT_ALERT";
  sourceAccountId: string | null;
};

export type BudgetAlertFormState = FormBase & {
  ruleType: "BUDGET_ALERT";
  budgetId: string | null;
};

export type RuleFormState =
  | AllocationFormState
  | FloorFormState
  | OvercommitmentFormState
  | BudgetAlertFormState;

// ----------------------------------------------------------- defaults

// CONFIRM is the default and is listed first (decision Q11, M02).
export const MODE_ORDER: readonly ExecutionMode[] = ["CONFIRM", "AUTO"];

export function emptyFormState(type: RuleType): RuleFormState {
  switch (type) {
    case "INCOME_ALLOCATION":
      return {
        ruleType: type,
        name: "",
        description: "",
        sourceAccountId: null,
        executionMode: "CONFIRM",
        policy: "FIXED_PER_GOAL",
        percent: "",
        targets: [],
        incomeSources: [...DEFAULT_INCOME_SOURCES],
        capAtTarget: true,
        allowPartial: false,
        effectiveFrom: "",
      };
    case "MINIMUM_UNALLOCATED_FLOOR":
      return { ruleType: type, name: "", description: "", sourceAccountId: null, floorAmount: "" };
    case "OVERCOMMITMENT_ALERT":
      return { ruleType: type, name: "", description: "", sourceAccountId: null };
    case "BUDGET_ALERT":
      return { ruleType: type, name: "", description: "", budgetId: null };
    default:
      return assertNever(type, "rule type");
  }
}

export function formStateFromRule(rule: FinancialRule): RuleFormState {
  const base = { name: rule.name, description: rule.description ?? "" };

  switch (rule.rule_type) {
    case "INCOME_ALLOCATION":
      return {
        ...base,
        ruleType: rule.rule_type,
        sourceAccountId: rule.source_account_id,
        executionMode: rule.execution_mode,
        policy: rule.policy,
        percent: rule.percent ?? "",
        targets: [...rule.targets]
          .sort((a, b) => a.position - b.position)
          .map((target) => ({ goalId: target.goal_id, amount: target.amount_or_cap ?? "" })),
        incomeSources: INCOME_SOURCES.filter((source) => rule.income_sources.includes(source)),
        capAtTarget: rule.cap_at_target,
        allowPartial: rule.allow_partial,
        effectiveFrom: rule.effective_from ?? "",
      };
    case "MINIMUM_UNALLOCATED_FLOOR":
      return { ...base, ruleType: rule.rule_type, sourceAccountId: rule.source_account_id, floorAmount: rule.floor_amount };
    case "OVERCOMMITMENT_ALERT":
      return { ...base, ruleType: rule.rule_type, sourceAccountId: rule.source_account_id };
    case "BUDGET_ALERT":
      return { ...base, ruleType: rule.rule_type, budgetId: rule.budget_id };
    default:
      return assertNever(rule, "rule");
  }
}

// --------------------------------------------------------- activation gate

// AUTO may be saved as a configuration, but it must never become the mode of
// a rule that is on or paused (that would be a path to AUTO without Preview).
// Draft and Off rules may be set to AUTO; turning them on is gated separately
// (financial-rule-actions.ts) until F5 ships Preview.
export function allowedModes(status: RuleStatus | null): ExecutionMode[] {
  return status === "enabled" || status === "paused" ? ["CONFIRM"] : [...MODE_ORDER];
}

export const MODE_LOCKED_MESSAGE =
  "A rule that is on or paused can only be set to 'Ask me first'. Turn the rule off first to change it to Automatic.";

export class AutoActivationBlockedError extends Error {
  constructor() {
    super(MODE_LOCKED_MESSAGE);
    this.name = "AutoActivationBlockedError";
  }
}

// ----------------------------------------------------------- validation

export type FormErrors = Record<string, string>;

const MONEY_PATTERN = /^\d{1,10}(\.\d{1,2})?$/;
const PERCENT_PATTERN = /^\d{1,3}(\.\d{1,2})?$/;
const DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;

const hasNonZeroDigit = (value: string): boolean => /[1-9]/.test(value);

export function isPositiveMoney(value: string): boolean {
  return MONEY_PATTERN.test(value) && hasNonZeroDigit(value);
}

export function isNonNegativeMoney(value: string): boolean {
  return MONEY_PATTERN.test(value);
}

// Text test only: 0 < percent <= 100 with at most two decimals.
export function isValidPercent(value: string): boolean {
  if (!PERCENT_PATTERN.test(value) || !hasNonZeroDigit(value)) {
    return false;
  }

  const [whole, fraction = ""] = value.split(".");
  const integer = Number.parseInt(whole, 10);

  return integer < 100 || (integer === 100 && /^0*$/.test(fraction));
}

export function isValidIsoDate(value: string): boolean {
  const match = DATE_PATTERN.exec(value);

  if (!match) {
    return false;
  }

  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const date = new Date(Date.UTC(year, month - 1, day));

  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

export type ValidationContext = { status?: RuleStatus; originalMode?: ExecutionMode };

export const ERROR_TEXT = {
  nameRequired: "Enter a name.",
  nameTooLong: `Use at most ${MAX_NAME_LENGTH} characters.`,
  descriptionTooLong: `Use at most ${MAX_DESCRIPTION_LENGTH} characters.`,
  accountRequired: "Choose an Account.",
  budgetRequired: "Choose a Budget.",
  floorInvalid: "Enter an amount of 0 or more, with at most 2 decimals.",
  percentInvalid: "Enter a percent above 0 and up to 100, with at most 2 decimals.",
  targetsRequired: "Choose at least one Goal.",
  targetsTooMany: `Choose at most ${MAX_TARGETS_PER_RULE} Goals.`,
  targetsDuplicate: "Each Goal can be added only once.",
  targetAmountRequired: "Enter an amount above 0, with at most 2 decimals.",
  targetCapInvalid: "Enter a cap above 0 with at most 2 decimals, or leave it empty.",
  sourcesRequired: "Choose at least one income source.",
  dateInvalid: "Use a real date as YYYY-MM-DD, or leave it empty.",
} as const;

export function validateRuleForm(state: RuleFormState, context: ValidationContext = {}): FormErrors {
  const errors: FormErrors = {};
  const name = state.name.trim();

  if (name.length === 0) {
    errors.name = ERROR_TEXT.nameRequired;
  } else if (name.length > MAX_NAME_LENGTH) {
    errors.name = ERROR_TEXT.nameTooLong;
  }

  if (state.description.trim().length > MAX_DESCRIPTION_LENGTH) {
    errors.description = ERROR_TEXT.descriptionTooLong;
  }

  switch (state.ruleType) {
    case "INCOME_ALLOCATION":
      validateAllocation(state, context, errors);
      break;
    case "MINIMUM_UNALLOCATED_FLOOR":
      if (state.sourceAccountId === null) errors.sourceAccountId = ERROR_TEXT.accountRequired;
      if (!isNonNegativeMoney(state.floorAmount.trim())) errors.floorAmount = ERROR_TEXT.floorInvalid;
      break;
    case "OVERCOMMITMENT_ALERT":
      if (state.sourceAccountId === null) errors.sourceAccountId = ERROR_TEXT.accountRequired;
      break;
    case "BUDGET_ALERT":
      if (state.budgetId === null) errors.budgetId = ERROR_TEXT.budgetRequired;
      break;
    default:
      return assertNever(state, "form state");
  }

  return errors;
}

function validateAllocation(state: AllocationFormState, context: ValidationContext, errors: FormErrors): void {
  if (state.sourceAccountId === null) errors.sourceAccountId = ERROR_TEXT.accountRequired;

  if (
    (context.status === "enabled" || context.status === "paused") &&
    state.executionMode === "AUTO" &&
    context.originalMode !== "AUTO"
  ) {
    errors.executionMode = MODE_LOCKED_MESSAGE;
  }

  if (state.policy === "PERCENT_OF_INCOME_WATERFALL" && !isValidPercent(state.percent.trim())) {
    errors.percent = ERROR_TEXT.percentInvalid;
  }

  if (state.targets.length === 0) {
    errors.targets = ERROR_TEXT.targetsRequired;
  } else if (state.targets.length > MAX_TARGETS_PER_RULE) {
    errors.targets = ERROR_TEXT.targetsTooMany;
  } else if (new Set(state.targets.map((target) => target.goalId)).size !== state.targets.length) {
    errors.targets = ERROR_TEXT.targetsDuplicate;
  }

  for (const target of state.targets) {
    const amount = target.amount.trim();

    if (state.policy === "FIXED_PER_GOAL") {
      if (!isPositiveMoney(amount)) errors[`target:${target.goalId}`] = ERROR_TEXT.targetAmountRequired;
    } else if (amount !== "" && !isPositiveMoney(amount)) {
      errors[`target:${target.goalId}`] = ERROR_TEXT.targetCapInvalid;
    }
  }

  if (state.incomeSources.length === 0) errors.incomeSources = ERROR_TEXT.sourcesRequired;

  const date = state.effectiveFrom.trim();

  if (date !== "" && !isValidIsoDate(date)) errors.effectiveFrom = ERROR_TEXT.dateInvalid;
}

export const isFormValid = (errors: FormErrors): boolean => Object.keys(errors).length === 0;

// ------------------------------------------------------ request building

const trimmedOrNull = (value: string): string | null => (value.trim() === "" ? null : value.trim());

function targetInputs(state: AllocationFormState) {
  return state.targets.map((target, position) => {
    const amount = trimmedOrNull(target.amount);

    return amount === null
      ? { goal_id: target.goalId, position }
      : { goal_id: target.goalId, amount_or_cap: amount, position };
  });
}

function requireValid(state: RuleFormState, context: ValidationContext = {}): void {
  if (!isFormValid(validateRuleForm(state, context))) {
    throw new RangeError("The rule form is not valid.");
  }
}

// A new rule is always created as a draft (the backend decides status).
export function buildCreateRequest(state: RuleFormState): FinancialRuleCreate {
  requireValid(state);

  const base = { name: state.name.trim(), ...(trimmedOrNull(state.description) === null ? {} : { description: state.description.trim() }) };

  switch (state.ruleType) {
    case "INCOME_ALLOCATION": {
      const effectiveFrom = trimmedOrNull(state.effectiveFrom);

      return {
        ...base,
        rule_type: "INCOME_ALLOCATION",
        source_account_id: state.sourceAccountId as string,
        execution_mode: state.executionMode,
        policy: state.policy,
        ...(state.policy === "PERCENT_OF_INCOME_WATERFALL" ? { percent: state.percent.trim() } : {}),
        cap_at_target: state.capAtTarget,
        allow_partial: state.allowPartial,
        income_sources: INCOME_SOURCES.filter((source) => state.incomeSources.includes(source)),
        ...(effectiveFrom === null ? {} : { effective_from: effectiveFrom }),
        targets: targetInputs(state),
      };
    }
    case "MINIMUM_UNALLOCATED_FLOOR":
      return {
        ...base,
        rule_type: "MINIMUM_UNALLOCATED_FLOOR",
        source_account_id: state.sourceAccountId as string,
        floor_amount: state.floorAmount.trim(),
      };
    case "OVERCOMMITMENT_ALERT":
      return { ...base, rule_type: "OVERCOMMITMENT_ALERT", source_account_id: state.sourceAccountId as string };
    case "BUDGET_ALERT":
      return { ...base, rule_type: "BUDGET_ALERT", budget_id: state.budgetId as string };
    default:
      return assertNever(state, "form state");
  }
}

// Text-only normal form so "300" and "300.00" compare equal. Never a number.
export function normalizeDecimal(value: string | null): string | null {
  if (value === null) {
    return null;
  }

  const [whole, fraction = ""] = value.trim().split(".");
  const integer = whole.replace(/^0+(?=\d)/, "");
  const decimals = fraction.replace(/0+$/, "");

  return decimals === "" ? integer : `${integer}.${decimals}`;
}

export type UpdatePlan = {
  update: FinancialRuleUpdate;
  // PATCH field names that differ from the stored rule.
  changedFields: string[];
};

const sameList = (a: readonly unknown[], b: readonly unknown[]): boolean =>
  a.length === b.length && a.every((item, index) => item === b[index]);

// Only the fields that changed (the backend merges the rest). Throws
// AutoActivationBlockedError when the edit would make an on/paused rule
// Automatic, and RangeError for an invalid form.
export function buildUpdatePlan(original: FinancialRule, state: RuleFormState): UpdatePlan {
  if (original.rule_type !== state.ruleType) {
    throw new RangeError("A rule's type cannot be changed.");
  }

  if (
    original.rule_type === "INCOME_ALLOCATION" &&
    state.ruleType === "INCOME_ALLOCATION" &&
    (original.status === "enabled" || original.status === "paused") &&
    state.executionMode === "AUTO" &&
    original.execution_mode !== "AUTO"
  ) {
    throw new AutoActivationBlockedError();
  }

  requireValid(state, {
    status: original.status,
    originalMode: original.rule_type === "INCOME_ALLOCATION" ? original.execution_mode : undefined,
  });

  const update: FinancialRuleUpdate = {};
  const name = state.name.trim();
  const description = trimmedOrNull(state.description);

  if (name !== original.name) update.name = name;
  if (description !== original.description) update.description = description;

  switch (state.ruleType) {
    case "INCOME_ALLOCATION":
      planAllocation(original as IncomeAllocationRule, state, update);
      break;
    case "MINIMUM_UNALLOCATED_FLOOR":
      if (original.rule_type === "MINIMUM_UNALLOCATED_FLOOR") {
        if (state.sourceAccountId !== original.source_account_id) update.source_account_id = state.sourceAccountId as string;
        if (normalizeDecimal(state.floorAmount) !== normalizeDecimal(original.floor_amount)) update.floor_amount = state.floorAmount.trim();
      }
      break;
    case "OVERCOMMITMENT_ALERT":
      if (original.rule_type === "OVERCOMMITMENT_ALERT" && state.sourceAccountId !== original.source_account_id) {
        update.source_account_id = state.sourceAccountId as string;
      }
      break;
    case "BUDGET_ALERT":
      if (original.rule_type === "BUDGET_ALERT" && state.budgetId !== original.budget_id) {
        update.budget_id = state.budgetId as string;
      }
      break;
    default:
      return assertNever(state, "form state");
  }

  return { update, changedFields: Object.keys(update) };
}

function planAllocation(original: IncomeAllocationRule, state: AllocationFormState, update: FinancialRuleUpdate): void {
  if (state.sourceAccountId !== original.source_account_id) update.source_account_id = state.sourceAccountId as string;
  if (state.executionMode !== original.execution_mode) update.execution_mode = state.executionMode;
  if (state.policy !== original.policy) update.policy = state.policy;

  // Switching to the fixed policy must CLEAR a stored percent, or the merged
  // rule is invalid.
  const percent = state.policy === "PERCENT_OF_INCOME_WATERFALL" ? normalizeDecimal(state.percent) : null;

  if (percent !== normalizeDecimal(original.percent)) {
    update.percent = percent === null ? null : state.percent.trim();
  }

  if (state.capAtTarget !== original.cap_at_target) update.cap_at_target = state.capAtTarget;
  if (state.allowPartial !== original.allow_partial) update.allow_partial = state.allowPartial;

  const sources = INCOME_SOURCES.filter((source) => state.incomeSources.includes(source));
  const originalSources = INCOME_SOURCES.filter((source) => original.income_sources.includes(source));

  if (!sameList(sources, originalSources)) update.income_sources = sources;

  const effectiveFrom = trimmedOrNull(state.effectiveFrom);

  if (effectiveFrom !== original.effective_from) update.effective_from = effectiveFrom;

  const wanted = state.targets.map((target) => `${target.goalId}|${normalizeDecimal(trimmedOrNull(target.amount)) ?? ""}`);
  const stored = [...original.targets]
    .sort((a, b) => a.position - b.position)
    .map((target) => `${target.goal_id}|${normalizeDecimal(target.amount_or_cap) ?? ""}`);

  if (!sameList(wanted, stored)) update.targets = targetInputs(state);
}

// ------------------------------------------------------------- notices

export const MATERIAL_EDIT_NOTICE =
  "Changing this rule replaces any suggestions that are still waiting for you.";

// Shown BEFORE saving: an on/paused allocation rule being edited in a field
// that changes its financial meaning (backend: version + 1, open proposals
// superseded). Pass the fields the form would change.
export function needsMaterialEditNotice(
  original: Pick<FinancialRule, "rule_type" | "status">,
  changedFields: readonly string[],
): boolean {
  return (
    original.rule_type === "INCOME_ALLOCATION" &&
    (original.status === "enabled" || original.status === "paused") &&
    isMaterialRuleEdit(changedFields)
  );
}

// The fields a form would change, or [] while the form is not valid enough to
// plan (used only to decide whether to show the notice).
export function previewChangedFields(original: FinancialRule, state: RuleFormState): string[] {
  try {
    return buildUpdatePlan(original, state).changedFields;
  } catch {
    return [];
  }
}
