import { Pressable, Text, TextInput, View } from "react-native";

import { styles } from "../goals/goals.styles";
import { FORM_NOT_PAID, scheduleLabel } from "./future-obligation-view";
import { MAX_DESCRIPTION_LENGTH, MAX_NAME_LENGTH, type FutureObligationFormValues } from "./future-obligation-validation";
import type { ObligationSchedule } from "./future-obligation.types";

const SCHEDULES: ObligationSchedule[] = ["monthly", "one_time"];

// VF-GOALS-PLANNING-002C1: the fields of the add/edit bill form. Presentational and
// controlled: the screen owns the values, validation and the request. Amounts are
// typed text and stay text.
export function FutureObligationForm({
  values,
  onChange,
  schedule,
  onScheduleChange,
  baseCurrency,
}: {
  values: FutureObligationFormValues;
  onChange: (values: FutureObligationFormValues) => void;
  // The kind of bill. On create the user chooses; on edit it is fixed (pass no
  // onScheduleChange) and shown as plain text.
  schedule: ObligationSchedule;
  onScheduleChange?: (schedule: ObligationSchedule) => void;
  baseCurrency: string | null;
}) {
  const set = <K extends keyof FutureObligationFormValues>(key: K, value: FutureObligationFormValues[K]) =>
    onChange({ ...values, [key]: value });
  const isMonthly = schedule === "monthly";

  return (
    <View>
      <Text style={styles.helperText}>* Required fields</Text>

      <View style={styles.formGroup}>
        <Text style={styles.label}>Kind of bill *</Text>

        {onScheduleChange ? (
          <View style={styles.typeToggleRow}>
            {SCHEDULES.map((option) => (
              <Pressable
                key={option}
                accessibilityRole="button"
                accessibilityLabel={`${scheduleLabel(option)} bill`}
                accessibilityState={{ selected: schedule === option }}
                style={[styles.typeToggleButton, schedule === option && styles.typeToggleButtonSelected]}
                onPress={() => onScheduleChange(option)}
              >
                <Text style={[styles.typeToggleButtonText, schedule === option && styles.typeToggleButtonTextSelected]}>
                  {scheduleLabel(option)}
                </Text>
              </Pressable>
            ))}
          </View>
        ) : (
          <Text style={styles.overviewText}>{scheduleLabel(schedule)} (this cannot be changed)</Text>
        )}

        <Text style={styles.overviewHelperText}>
          {isMonthly
            ? "Due every month, such as rent or a subscription."
            : "Due once, such as an insurance renewal or a repair."}
        </Text>
      </View>

      <View style={styles.formGroup}>
        <Text style={styles.label}>Name *</Text>
        <TextInput
          style={styles.input}
          placeholder="For example: Rent"
          value={values.name}
          onChangeText={(text) => set("name", text)}
          maxLength={MAX_NAME_LENGTH}
          accessibilityLabel="Bill name"
        />
      </View>

      <View style={styles.formGroup}>
        <Text style={styles.label}>{isMonthly ? "Amount each month *" : "Amount *"}</Text>
        <TextInput
          style={styles.input}
          placeholder="0.00"
          value={values.amount}
          onChangeText={(text) => set("amount", text)}
          keyboardType="decimal-pad"
          accessibilityLabel="Bill amount"
        />
      </View>

      <View style={styles.formGroup}>
        <Text style={styles.label}>Currency</Text>
        <TextInput
          style={styles.input}
          placeholder={baseCurrency ?? "EUR"}
          value={values.currency}
          onChangeText={(text) => set("currency", text)}
          autoCapitalize="characters"
          maxLength={3}
          accessibilityLabel="Bill currency"
        />
        <Text style={styles.overviewHelperText}>
          {baseCurrency
            ? `Leave blank to use your base currency (${baseCurrency}). Different currencies are never added together.`
            : "Leave blank to use your base currency. Different currencies are never added together."}
        </Text>
      </View>

      <View style={styles.formGroup}>
        <Text style={styles.label}>{isMonthly ? "First due date *" : "Due date *"}</Text>
        <TextInput
          style={styles.input}
          placeholder="YYYY-MM-DD"
          value={values.firstDueDate}
          onChangeText={(text) => set("firstDueDate", text)}
          accessibilityLabel={isMonthly ? "First due date" : "Due date"}
        />
        {isMonthly ? (
          <Text style={styles.overviewHelperText}>
            It is due on this day every month. In a shorter month it falls on the last day of that month.
          </Text>
        ) : null}
      </View>

      {isMonthly ? (
        <View style={styles.formGroup}>
          <Text style={styles.label}>Last due date</Text>
          <TextInput
            style={[styles.input, styles.inputOptional]}
            placeholder="YYYY-MM-DD (optional)"
            value={values.finalDueDate}
            onChangeText={(text) => set("finalDueDate", text)}
            accessibilityLabel="Last due date"
          />
          <Text style={styles.overviewHelperText}>Optional. Leave blank if the bill has no end date.</Text>
        </View>
      ) : null}

      <View style={styles.formGroup}>
        <Text style={styles.label}>Note</Text>
        <TextInput
          style={[styles.input, styles.inputOptional]}
          placeholder="Optional note"
          value={values.description}
          onChangeText={(text) => set("description", text)}
          maxLength={MAX_DESCRIPTION_LENGTH}
          accessibilityLabel="Bill note"
        />
      </View>

      <Text style={styles.overviewHelperText}>{FORM_NOT_PAID}</Text>
    </View>
  );
}
