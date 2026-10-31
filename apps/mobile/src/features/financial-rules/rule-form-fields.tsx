import { Pressable, Switch, Text, TextInput, View } from "react-native";

import { MODE_COPY, POLICY_COPY, SOURCE_COPY } from "./financial-rule-copy";
import { MODE_LOCKED_MESSAGE, allowedModes } from "./financial-rule-form";
import {
  INCOME_SOURCES,
  RULE_POLICIES,
  type ExecutionMode,
  type IncomeSource,
  type RulePolicy,
  type RuleStatus,
} from "./financial-rule.types";
import { styles } from "./rules.styles";

type FieldProps = {
  label: string;
  value: string;
  onChangeText: (value: string) => void;
  error?: string;
  helper?: string;
  placeholder?: string;
  keyboardType?: "default" | "decimal-pad";
  editable?: boolean;
  maxLength?: number;
  multiline?: boolean;
  optional?: boolean;
};

export function TextField({
  label,
  value,
  onChangeText,
  error,
  helper,
  placeholder,
  keyboardType = "default",
  editable = true,
  maxLength,
  optional = false,
}: FieldProps) {
  return (
    <View style={styles.formGroup}>
      <Text style={styles.label} accessibilityRole="header">
        {label}
      </Text>
      <TextInput
        accessibilityLabel={label}
        accessibilityHint={helper}
        style={[styles.input, optional && styles.inputOptional]}
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        keyboardType={keyboardType}
        editable={editable}
        maxLength={maxLength}
        autoCapitalize="none"
        autoCorrect={false}
      />
      {helper ? <Text style={styles.helperText}>{helper}</Text> : null}
      <FieldError message={error} />
    </View>
  );
}

export function FieldError({ message }: { message?: string }) {
  if (!message) {
    return null;
  }

  return (
    <Text style={styles.errorText} accessibilityLiveRegion="polite" accessibilityRole="alert">
      {message}
    </Text>
  );
}

type ModeSelectorProps = {
  value: ExecutionMode;
  status: RuleStatus | null;
  onChange: (mode: ExecutionMode) => void;
  error?: string;
};

// CONFIRM first. For a rule that is on or paused only CONFIRM is offered, so
// editing can never make such a rule Automatic.
export function ModeSelector({ value, status, onChange, error }: ModeSelectorProps) {
  const modes = allowedModes(status);
  const locked = status === "enabled" || status === "paused";

  return (
    <View style={styles.formGroup}>
      <Text style={styles.label} accessibilityRole="header">
        What should happen when income arrives?
      </Text>
      {modes.map((mode) => {
        const selected = value === mode;

        return (
          <Pressable
            key={mode}
            accessibilityRole="radio"
            accessibilityState={{ checked: selected }}
            accessibilityLabel={`${MODE_COPY[mode].label}. ${MODE_COPY[mode].description}`}
            style={[styles.card, selected && styles.chipSelected]}
            onPress={() => onChange(mode)}
          >
            <Text style={styles.name}>{selected ? `✓ ${MODE_COPY[mode].label}` : MODE_COPY[mode].label}</Text>
            <Text style={styles.secondaryText}>{MODE_COPY[mode].description}</Text>
          </Pressable>
        );
      })}
      {locked ? <Text style={styles.helperText}>{MODE_LOCKED_MESSAGE}</Text> : null}
      <FieldError message={error} />
    </View>
  );
}

export function PolicySelector({
  value,
  onChange,
}: {
  value: RulePolicy;
  onChange: (policy: RulePolicy) => void;
}) {
  return (
    <View style={styles.formGroup}>
      <Text style={styles.label} accessibilityRole="header">
        How much to reserve
      </Text>
      <View style={styles.typeToggleRow}>
        {RULE_POLICIES.map((policy) => {
          const selected = value === policy;

          return (
            <Pressable
              key={policy}
              accessibilityRole="radio"
              accessibilityState={{ checked: selected }}
              accessibilityLabel={POLICY_COPY[policy].label}
              style={[styles.typeToggleButton, selected && styles.typeToggleButtonSelected]}
              onPress={() => onChange(policy)}
            >
              <Text
                style={[styles.typeToggleButtonText, selected && styles.typeToggleButtonTextSelected]}
              >
                {POLICY_COPY[policy].label}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

export function IncomeSourceChips({
  value,
  onChange,
  error,
}: {
  value: IncomeSource[];
  onChange: (sources: IncomeSource[]) => void;
  error?: string;
}) {
  return (
    <View style={styles.formGroup}>
      <Text style={styles.label} accessibilityRole="header">
        Income sources
      </Text>
      <View style={styles.chipRow}>
        {INCOME_SOURCES.map((source) => {
          const selected = value.includes(source);

          return (
            <Pressable
              key={source}
              accessibilityRole="checkbox"
              accessibilityState={{ checked: selected }}
              accessibilityLabel={SOURCE_COPY[source]}
              style={[styles.chip, selected && styles.chipSelected]}
              onPress={() =>
                onChange(selected ? value.filter((item) => item !== source) : [...value, source])
              }
            >
              <Text style={[styles.chipText, selected && styles.chipTextSelected]}>
                {selected ? `✓ ${SOURCE_COPY[source]}` : SOURCE_COPY[source]}
              </Text>
            </Pressable>
          );
        })}
      </View>
      <FieldError message={error} />
    </View>
  );
}

export function SwitchRow({
  label,
  helper,
  value,
  onChange,
}: {
  label: string;
  helper: string;
  value: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <View>
      <View style={styles.switchRow}>
        <Text style={styles.switchLabel}>{label}</Text>
        <Switch
          accessibilityRole="switch"
          accessibilityLabel={label}
          accessibilityHint={helper}
          value={value}
          onValueChange={onChange}
        />
      </View>
      <Text style={styles.helperText}>{helper}</Text>
    </View>
  );
}
