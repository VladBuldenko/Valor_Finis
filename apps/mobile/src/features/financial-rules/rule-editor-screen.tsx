import { useRef, useState } from "react";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  SafeAreaView,
  ScrollView,
  Text,
  View,
} from "react-native";

import { useAuth } from "../auth/auth-context";
import { applyRuleChangeInvalidation, createSubmitGuard } from "./financial-rule-actions";
import { COPY } from "./financial-rule-copy";
import { describeRuleError } from "./financial-rule-errors";
import {
  MATERIAL_EDIT_NOTICE,
  buildCreateRequest,
  buildUpdatePlan,
  emptyFormState,
  formStateFromRule,
  isFormValid,
  needsMaterialEditNotice,
  previewChangedFields,
  validateRuleForm,
  type AllocationFormState,
  type RuleFormState,
} from "./financial-rule-form";
import { financialRuleKeys } from "./financial-rule-query-keys";
import { isMaterialRuleEdit, ruleTypeLabel } from "./financial-rule-presentation";
import { financialRulesService } from "./financial-rule.service";
import { RULE_TYPES, type FinancialRule, type RuleType } from "./financial-rule.types";
import { OptionPicker, type PickerOption } from "./option-picker";
import {
  FieldError,
  IncomeSourceChips,
  ModeSelector,
  PolicySelector,
  SwitchRow,
  TextField,
} from "./rule-form-fields";
import { styles } from "./rules.styles";
import { useRuleFormData } from "./use-rule-form-data";

const SIGNED_OUT_KEY = ["financial-rules", "signed-out"] as const;

type EditorProps =
  | { mode: "create"; ruleType: RuleType }
  | { mode: "edit"; rule: FinancialRule };

function RuleEditorForm(props: EditorProps) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { session } = useAuth();
  const userId = session?.user.id;
  const data = useRuleFormData();
  const original = props.mode === "edit" ? props.rule : null;
  const [form, setForm] = useState<RuleFormState>(() =>
    props.mode === "edit" ? formStateFromRule(props.rule) : emptyFormState(props.ruleType),
  );
  const [showErrors, setShowErrors] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const guard = useRef(createSubmitGuard()).current;

  const context =
    original && original.rule_type === "INCOME_ALLOCATION"
      ? { status: original.status, originalMode: original.execution_mode }
      : { status: original?.status };
  const errors = validateRuleForm(form, context);
  const visibleErrors = showErrors ? errors : {};

  const saveMutation = useMutation({
    mutationFn: async (): Promise<{ rule: FinancialRule; material: boolean; created: boolean }> => {
      if (original) {
        const plan = buildUpdatePlan(original, form);

        if (plan.changedFields.length === 0) {
          return { rule: original, material: false, created: false };
        }

        const rule = await financialRulesService.updateRule(original.id, plan.update);

        return { rule, material: isMaterialRuleEdit(plan.changedFields), created: false };
      }

      const rule = await financialRulesService.createRule(buildCreateRequest(form));

      return { rule, material: false, created: true };
    },
    onSuccess: async ({ rule, material, created }) => {
      if (userId) {
        await applyRuleChangeInvalidation(
          queryClient,
          userId,
          created ? { kind: "created", rule } : { kind: "edited", rule, material },
        );
      }

      router.replace({ pathname: "/rules/[id]", params: { id: rule.id } });
    },
    onError: (error) => {
      // Inputs are kept: the form state is untouched. Nothing is retried.
      setSubmitError(describeRuleError(error, "Unable to save the rule.", { mutation: true }).message);
    },
    onSettled: () => guard.leave(),
  });

  function update(patch: Partial<AllocationFormState> & Record<string, unknown>) {
    setForm((current) => ({ ...current, ...patch }) as RuleFormState);
    setSubmitError(null);
  }

  function handleSave() {
    if (!guard.tryEnter()) {
      return;
    }

    setShowErrors(true);
    setSubmitError(null);

    if (!isFormValid(errors)) {
      guard.leave();

      return;
    }

    saveMutation.mutate();
  }

  if (data.isLoading) {
    return <ActivityIndicator style={styles.loader} />;
  }

  if (data.isError) {
    return (
      <View style={styles.content}>
        <Text style={styles.errorText}>Could not load your Accounts, Goals and Budgets.</Text>
        <Pressable accessibilityRole="button" style={styles.button} onPress={data.refetchAll}>
          <Text style={styles.buttonText}>Retry</Text>
        </Pressable>
      </View>
    );
  }

  const accounts = (data.accounts.data ?? []).filter(
    (account) =>
      account.status === "active" ||
      ("sourceAccountId" in form && account.id === form.sourceAccountId),
  );
  const accountOptions: PickerOption[] = accounts.map((account) => ({
    id: account.id,
    label: `${account.name} — ${account.currency}`,
  }));
  const budgetOptions: PickerOption[] = (data.budgets.data ?? []).map((budget) => ({
    id: budget.id,
    label: `${budget.name} — ${budget.currency}`,
  }));
  const isSaving = saveMutation.isPending;
  const changed = original ? previewChangedFields(original, form) : [];
  const showMaterialNotice = original ? needsMaterialEditNotice(original, changed) : false;

  return (
    <SafeAreaView style={styles.container}>
      <KeyboardAvoidingView
        style={styles.container}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <Text style={styles.title} accessibilityRole="header">
            {original ? "Edit rule" : ruleTypeLabel(form.ruleType)}
          </Text>

          <TextField
            label="Name"
            value={form.name}
            onChangeText={(name) => update({ name })}
            error={visibleErrors.name}
            maxLength={150}
            editable={!isSaving}
          />
          <TextField
            label="Description (optional)"
            value={form.description}
            onChangeText={(description) => update({ description })}
            error={visibleErrors.description}
            maxLength={255}
            editable={!isSaving}
            optional
          />

          {form.ruleType === "BUDGET_ALERT" ? (
            <View style={styles.formGroup}>
              <Text style={styles.label} accessibilityRole="header">Budget</Text>
              <OptionPicker
                title="Select budget"
                placeholder="Choose a Budget"
                options={budgetOptions}
                selectedId={form.budgetId}
                onChange={(budgetId) => update({ budgetId })}
                disabled={isSaving}
              />
              <FieldError message={visibleErrors.budgetId} />
            </View>
          ) : (
            <View style={styles.formGroup}>
              <Text style={styles.label} accessibilityRole="header">Account</Text>
              <OptionPicker
                title="Select account"
                placeholder="Choose an Account"
                options={accountOptions}
                selectedId={form.sourceAccountId}
                onChange={(sourceAccountId) => update({ sourceAccountId })}
                disabled={isSaving}
              />
              <FieldError message={visibleErrors.sourceAccountId} />
            </View>
          )}

          {form.ruleType === "MINIMUM_UNALLOCATED_FLOOR" ? (
            <TextField
              label="Minimum unallocated floor"
              value={form.floorAmount}
              onChangeText={(floorAmount) => update({ floorAmount })}
              error={visibleErrors.floorAmount}
              keyboardType="decimal-pad"
              helper="A threshold you set. It does not remove money from the Account; you will see a warning when a reservation would leave less available to reserve."
              editable={!isSaving}
            />
          ) : null}

          {form.ruleType === "OVERCOMMITMENT_ALERT" ? (
            <Text style={styles.helperText}>
              You will get an alert when more is reserved for Goals in this Account than it can cover.
            </Text>
          ) : null}

          {form.ruleType === "BUDGET_ALERT" ? (
            <Text style={styles.helperText}>
              You will get an alert as this Budget gets close to, or goes over, its limit.
            </Text>
          ) : null}

          {form.ruleType === "INCOME_ALLOCATION" ? (
            <AllocationFields
              form={form}
              original={original}
              errors={visibleErrors}
              update={update}
              goals={data.goals.data ?? []}
              accounts={data.accounts.data ?? []}
              disabled={isSaving}
            />
          ) : null}

          {showMaterialNotice ? (
            <Text style={styles.noticeText} accessibilityLiveRegion="polite">
              {MATERIAL_EDIT_NOTICE}
            </Text>
          ) : null}

          {submitError ? (
            <Text style={styles.errorText} accessibilityLiveRegion="polite" accessibilityRole="alert">
              {submitError}
            </Text>
          ) : null}

          <Pressable
            accessibilityRole="button"
            accessibilityLabel={original ? "Save changes" : "Save as draft"}
            accessibilityState={{ disabled: isSaving, busy: isSaving }}
            disabled={isSaving}
            style={[styles.button, isSaving && styles.disabledButton]}
            onPress={handleSave}
          >
            {isSaving ? (
              <ActivityIndicator />
            ) : (
              <Text style={styles.buttonText}>{original ? "Save changes" : "Save as draft"}</Text>
            )}
          </Pressable>

          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Cancel"
            disabled={isSaving}
            style={styles.editButton}
            onPress={() => router.back()}
          >
            <Text style={styles.editButtonText}>Cancel</Text>
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

type AllocationFieldsProps = {
  form: AllocationFormState;
  original: FinancialRule | null;
  errors: Record<string, string>;
  update: (patch: Partial<AllocationFormState> & Record<string, unknown>) => void;
  goals: { id: string; name: string; currency: string; status: string }[];
  accounts: { id: string; currency: string }[];
  disabled: boolean;
};

function AllocationFields({ form, original, errors, update, goals, accounts, disabled }: AllocationFieldsProps) {
  const accountCurrency = accounts.find((account) => account.id === form.sourceAccountId)?.currency ?? null;
  const goalName = (goalId: string): string => goals.find((goal) => goal.id === goalId)?.name ?? "Unavailable Goal";
  const chosen = new Set(form.targets.map((target) => target.goalId));
  // Convenience filter only: the backend enforces active status and equal currencies.
  const goalOptions: PickerOption[] = goals
    .filter(
      (goal) =>
        goal.status !== "archived" &&
        !chosen.has(goal.id) &&
        (accountCurrency === null || goal.currency === accountCurrency),
    )
    .map((goal) => ({ id: goal.id, label: `${goal.name} — ${goal.currency}` }));
  const isFixed = form.policy === "FIXED_PER_GOAL";
  const status = original ? original.status : null;

  return (
    <>
      <Text style={styles.helperText}>{COPY.reservationMeaning}</Text>

      <ModeSelector
        value={form.executionMode}
        status={status}
        onChange={(executionMode) => update({ executionMode })}
        error={errors.executionMode}
      />

      <PolicySelector value={form.policy} onChange={(policy) => update({ policy })} />

      {!isFixed ? (
        <TextField
          label="Percent of each income (%)"
          value={form.percent}
          onChangeText={(percent) => update({ percent })}
          error={errors.percent}
          keyboardType="decimal-pad"
          helper="Goals are filled in priority order until this share of the income is used."
          editable={!disabled}
        />
      ) : null}

      <View style={styles.formGroup}>
        <Text style={styles.label} accessibilityRole="header">Goals to fund</Text>
        {form.targets.map((target) => (
          <View key={target.goalId} style={styles.targetRow}>
            <View style={styles.rowBetween}>
              <Text style={styles.name}>{goalName(target.goalId)}</Text>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`Remove ${goalName(target.goalId)}`}
                disabled={disabled}
                onPress={() =>
                  update({ targets: form.targets.filter((row) => row.goalId !== target.goalId) })
                }
              >
                <Text style={styles.buttonText}>Remove</Text>
              </Pressable>
            </View>
            <TextField
              label={isFixed ? `Amount for ${goalName(target.goalId)}` : `Cap for ${goalName(target.goalId)} (optional)`}
              value={target.amount}
              onChangeText={(amount) =>
                update({
                  targets: form.targets.map((row) =>
                    row.goalId === target.goalId ? { ...row, amount } : row,
                  ),
                })
              }
              error={errors[`target:${target.goalId}`]}
              keyboardType="decimal-pad"
              editable={!disabled}
              optional={!isFixed}
            />
          </View>
        ))}
        <View style={styles.formGroup}>
          <OptionPicker
            title="Add a Goal"
            placeholder="Add a Goal"
            options={goalOptions}
            selectedId={null}
            onChange={(goalId) => update({ targets: [...form.targets, { goalId, amount: "" }] })}
            disabled={disabled}
          />
        </View>
        <FieldError message={errors.targets} />
      </View>

      <IncomeSourceChips
        value={form.incomeSources}
        onChange={(incomeSources) => update({ incomeSources })}
        error={errors.incomeSources}
      />

      <SwitchRow
        label="Stop at each Goal's target"
        helper="A Goal that has reached its target gets nothing more."
        value={form.capAtTarget}
        onChange={(capAtTarget) => update({ capAtTarget })}
      />
      <SwitchRow
        label="Allow partial reservations"
        helper="When there is not enough available for every Goal, reserve for as many as fit instead of none."
        value={form.allowPartial}
        onChange={(allowPartial) => update({ allowPartial })}
      />

      <TextField
        label="Start from (optional)"
        value={form.effectiveFrom}
        onChangeText={(effectiveFrom) => update({ effectiveFrom })}
        error={errors.effectiveFrom}
        placeholder="YYYY-MM-DD"
        helper="Leave empty to start on the day the rule is first turned on."
        editable={!disabled}
        optional
      />
    </>
  );
}

// R-02..R-05 create: choose a rule type, then the matching editor.
export function RuleCreateScreen() {
  const [ruleType, setRuleType] = useState<RuleType | null>(null);

  if (ruleType === null) {
    return (
      <SafeAreaView style={styles.container}>
        <ScrollView contentContainerStyle={styles.content}>
          <Text style={styles.title} accessibilityRole="header">New rule</Text>
          <Text style={styles.secondaryText}>What should this rule do?</Text>
          {RULE_TYPES.map((type) => (
            <Pressable
              key={type}
              accessibilityRole="button"
              accessibilityLabel={ruleTypeLabel(type)}
              style={styles.card}
              onPress={() => setRuleType(type)}
            >
              <Text style={styles.name}>{ruleTypeLabel(type)}</Text>
              <Text style={styles.secondaryText}>{TYPE_DESCRIPTIONS[type]}</Text>
            </Pressable>
          ))}
        </ScrollView>
      </SafeAreaView>
    );
  }

  return <RuleEditorForm mode="create" ruleType={ruleType} />;
}

const TYPE_DESCRIPTIONS: Record<RuleType, string> = {
  INCOME_ALLOCATION: "Reserve part of your income for Goals, with your confirmation or on its own.",
  MINIMUM_UNALLOCATED_FLOOR: "Set an amount you want to keep unreserved in an Account.",
  OVERCOMMITMENT_ALERT: "Get an alert when an Account has more reserved than it can cover.",
  BUDGET_ALERT: "Get an alert as a Budget nears or passes its limit.",
};

// R-02..R-05 edit: the same editor, prefilled from the stored rule.
export function RuleEditScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { session } = useAuth();
  const userId = session?.user.id;
  const ruleQuery = useQuery({
    queryKey: userId ? financialRuleKeys.ruleDetail(userId, id) : SIGNED_OUT_KEY,
    queryFn: ({ signal }) => financialRulesService.getRule(id, signal),
    enabled: Boolean(userId) && Boolean(id),
  });

  if (ruleQuery.isLoading) {
    return <ActivityIndicator style={styles.loader} />;
  }

  if (ruleQuery.isError || !ruleQuery.data) {
    const message = describeRuleError(ruleQuery.error, "Could not load this rule.").message;

    return (
      <View style={styles.content}>
        <Text style={styles.errorText} accessibilityRole="alert">{message}</Text>
        <Pressable accessibilityRole="button" style={styles.button} onPress={() => void ruleQuery.refetch()}>
          <Text style={styles.buttonText}>Retry</Text>
        </Pressable>
      </View>
    );
  }

  // Keyed by id and version so a refreshed rule never leaves stale form state.
  return <RuleEditorForm key={`${ruleQuery.data.id}:${ruleQuery.data.version}`} mode="edit" rule={ruleQuery.data} />;
}

