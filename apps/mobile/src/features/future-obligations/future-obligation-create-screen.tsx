import { useRef, useState } from "react";
import * as Crypto from "expo-crypto";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  Text,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { describeCreateFailure } from "../../api/create-failure";
import {
  createSubmitGuard,
  resolveCreateAttempt,
  type CreateAttempt,
} from "../../lib/create-attempts";
import { useAuth } from "../auth/auth-context";
import { styles } from "../goals/goals.styles";
import { invalidateFutureObligationQueries } from "./future-obligation-cache";
import {
  futureObligationPayloadKey,
  toFutureObligationCreateInput,
  type FutureObligationCreatePayload,
} from "./future-obligation-create-attempt";
import { FutureObligationForm } from "./future-obligation-form";
import {
  buildCreatePayload,
  localIsoDate,
  validateFutureObligationForm,
  type FutureObligationFormValues,
} from "./future-obligation-validation";
import { createFutureObligation, getUpcomingObligations } from "./future-obligation.service";
import type { ObligationSchedule } from "./future-obligation.types";

// VF-GOALS-PLANNING-002C1: "Add a bill". Records a future obligation. Saving never
// pays it, sets money aside or adds an expense.
export function FutureObligationCreateScreen() {
  const { schedule: scheduleParam } = useLocalSearchParams<{ schedule?: string }>();
  const { session } = useAuth();
  const queryClient = useQueryClient();
  const router = useRouter();

  const [values, setValues] = useState<FutureObligationFormValues>(() => ({
    name: "",
    schedule: scheduleParam === "one_time" ? "one_time" : "monthly",
    amount: "",
    currency: "",
    firstDueDate: localIsoDate(new Date()),
    finalDueDate: "",
    description: "",
  }));

  // Create idempotency, as for Income and Expense: the attempts of this form are
  // kept across failed submissions, so a retry of the same bill reuses its
  // client_request_id and the backend returns the saved bill instead of adding a
  // second one. Refs, not state: they never affect rendering. The guard is
  // synchronous, unlike isPending, which only turns true after a re-render.
  const createAttemptsRef = useRef<CreateAttempt<FutureObligationCreatePayload>[]>([]);
  const submitGuardRef = useRef(createSubmitGuard());

  // Only to name the base currency in the hint; the form works without it.
  const upcomingQuery = useQuery({
    queryKey: ["future-obligations", session?.user.id, "upcoming"],
    queryFn: ({ signal }) => getUpcomingObligations(signal),
    enabled: Boolean(session),
  });

  const createMutation = useMutation({
    mutationFn: createFutureObligation,

    // 201 (new) and 200 (replay of an earlier, possibly lost, attempt) are the
    // same success: the body is the bill's current state either way.
    onSuccess: async () => {
      createAttemptsRef.current = [];
      await invalidateFutureObligationQueries(queryClient, session?.user.id);
      router.back();
    },

    // The attempts are kept on purpose: the bill may have been saved even though
    // the response was lost, so resubmitting the unchanged form reuses the key.
    onError: (mutationError) => {
      const failure = describeCreateFailure(mutationError, "bill", "Unable to save the bill.");

      if (failure.discardAttempt) {
        createAttemptsRef.current = [];
      }

      Alert.alert(failure.title, failure.message);
    },

    onSettled: () => {
      submitGuardRef.current.release();
    },
  });

  function handleSave() {
    if (createMutation.isPending || submitGuardRef.current.isBusy()) {
      return;
    }

    const validationError = validateFutureObligationForm(values);

    if (validationError) {
      Alert.alert("Check the bill", validationError);
      return;
    }

    if (!submitGuardRef.current.tryEnter()) {
      return;
    }

    try {
      const payload = buildCreatePayload(values);
      const { attempt, attempts } = resolveCreateAttempt(
        createAttemptsRef.current,
        session?.user.id ?? "",
        futureObligationPayloadKey(payload),
        payload,
        () => Crypto.randomUUID(),
      );

      createAttemptsRef.current = attempts;
      createMutation.mutate(toFutureObligationCreateInput(attempt));
    } catch (error) {
      // Nothing was sent (onSettled will not run), so the guard must not stay held.
      submitGuardRef.current.release();
      throw error;
    }
  }

  return (
    <SafeAreaView style={styles.container}>
      <KeyboardAvoidingView style={styles.container} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <Text style={styles.title}>Add a bill</Text>

          <FutureObligationForm
            values={values}
            onChange={setValues}
            schedule={values.schedule}
            onScheduleChange={(schedule: ObligationSchedule) => setValues({ ...values, schedule })}
            baseCurrency={upcomingQuery.data?.base_currency ?? null}
          />

          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Save bill"
            disabled={createMutation.isPending}
            onPress={handleSave}
            style={[styles.button, styles.formGroup]}
          >
            {createMutation.isPending ? <ActivityIndicator /> : <Text style={styles.buttonText}>Save bill</Text>}
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
