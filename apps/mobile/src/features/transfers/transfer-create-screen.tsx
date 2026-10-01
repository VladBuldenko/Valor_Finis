import { useRef, useState } from "react";
import * as Crypto from "expo-crypto";
import { useRouter } from "expo-router";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { getApiErrorMessage } from "../../api/api-error-message";
import { getAccounts } from "../accounts/account.service";
import type { Account } from "../accounts/account.types";
import { useAuth } from "../auth/auth-context";
import { formatLocalCalendarDate } from "./local-calendar-date";
import { TransferAccountPicker } from "./transfer-account-picker";
import { invalidateTransferQueries } from "./transfer-cache";
import {
  resolveTransferCreateAttempt,
  toAccountTransferCreateInput,
  type TransferCreateAttempt,
  type TransferCreatePayload,
} from "./transfer-create-attempts";
import {
  isTransferDateShape,
  prepareTransferCreatePayload,
} from "./transfer-validation";
import { createAccountTransfer } from "./transfer.service";
import { styles } from "./transfers.styles";

// Returns whether `destination` is a valid destination for `source`: a
// different active Account in the same currency. Currency is a UX guard
// only -- the backend enforces the same-currency rule itself.
function isValidDestination(
  destination: Account,
  source: Account | undefined,
): boolean {
  return (
    destination.status === "active" &&
    (source === undefined ||
      (destination.id !== source.id &&
        destination.currency === source.currency))
  );
}

// Whether at least two active Accounts share a currency, i.e. whether any
// transfer is possible at all (transfers are same-currency only).
function hasSameCurrencyPair(activeAccounts: Account[]): boolean {
  return activeAccounts.some((account) =>
    activeAccounts.some(
      (other) => other.id !== account.id && other.currency === account.currency,
    ),
  );
}

export function TransferCreateScreen() {
  const { session } = useAuth();
  const queryClient = useQueryClient();
  const router = useRouter();

  const [sourceAccountId, setSourceAccountId] = useState<string | null>(null);
  const [destinationAccountId, setDestinationAccountId] = useState<
    string | null
  >(null);
  const [amount, setAmount] = useState("");
  const [transferDate, setTransferDate] = useState(() =>
    formatLocalCalendarDate(new Date()),
  );
  const [description, setDescription] = useState("");

  // Create idempotency attempts of this form instance (see
  // resolveTransferCreateAttempt): kept across failed submissions so a
  // retry of the same payload reuses its client_request_id, cleared after
  // a success, and discarded when the screen closes. A ref, not state --
  // it never affects rendering and is only read in event handlers.
  const createAttemptsRef = useRef<TransferCreateAttempt[]>([]);

  const {
    data: accounts,
    isLoading: isAccountsLoading,
    error: accountsError,
  } = useQuery({
    queryKey: ["accounts", session?.user.id],
    queryFn: getAccounts,
    enabled: Boolean(session),
  });

  const createTransferMutation = useMutation({
    mutationFn: createAccountTransfer,

    // 201 (new) and 200 (exact replay of an earlier, possibly lost,
    // attempt) are the same success: the body is the transfer's current
    // state either way.
    onSuccess: async (transfer) => {
      createAttemptsRef.current = [];

      // Only a posted transfer wrote ledger rows; the server-returned
      // status (not the form's date) decides.
      await invalidateTransferQueries(
        queryClient,
        session?.user.id,
        transfer.status === "posted",
      );

      router.back();
    },

    // The attempts are deliberately kept: the request may have been
    // committed even though it failed here, so resubmitting the unchanged
    // form must reuse the same key.
    onError: (mutationError) => {
      Alert.alert(
        "Create transfer failed",
        getApiErrorMessage(mutationError, "Unable to create transfer."),
      );
    },
  });

  // Only active Accounts can take part in a new transfer. Selections are
  // resolved against the currently offered options, so an Account that was
  // archived or removed since it was picked is simply no longer selected.
  const activeAccounts = (accounts ?? []).filter(
    (account) => account.status === "active",
  );
  const sourceAccount = activeAccounts.find(
    (account) => account.id === sourceAccountId,
  );
  const destinationOptions = activeAccounts.filter((account) =>
    isValidDestination(account, sourceAccount),
  );
  const destinationAccount = destinationOptions.find(
    (account) => account.id === destinationAccountId,
  );

  const localToday = formatLocalCalendarDate(new Date());
  const trimmedTransferDate = transferDate.trim();
  const hasDateShape = isTransferDateShape(trimmedTransferDate);

  // Changing the source never changes it back or picks a replacement
  // destination: a destination that is no longer valid for the new source
  // (same Account, different currency, archived/unavailable) is cleared.
  function handleSourceChange(nextSourceId: string) {
    const nextSource = activeAccounts.find(
      (account) => account.id === nextSourceId,
    );
    const currentDestination = activeAccounts.find(
      (account) => account.id === destinationAccountId,
    );

    setSourceAccountId(nextSourceId);

    if (
      destinationAccountId !== null &&
      (currentDestination === undefined ||
        nextSource === undefined ||
        !isValidDestination(currentDestination, nextSource))
    ) {
      setDestinationAccountId(null);
    }
  }

  function submitPayload(payload: TransferCreatePayload) {
    if (createTransferMutation.isPending) {
      return;
    }

    const { attempt, attempts } = resolveTransferCreateAttempt(
      createAttemptsRef.current,
      payload,
      () => Crypto.randomUUID(),
    );

    createAttemptsRef.current = attempts;
    createTransferMutation.mutate(toAccountTransferCreateInput(attempt));
  }

  function handleCreateTransfer() {
    // Guards against duplicate submissions from a double tap while the
    // request is already in flight.
    if (createTransferMutation.isPending) {
      return;
    }

    const result = prepareTransferCreatePayload({
      sourceAccount,
      destinationAccount,
      amount,
      transferDate,
      description,
    });

    if ("error" in result) {
      Alert.alert("Invalid transfer", result.error);
      return;
    }

    // Already guaranteed by prepareTransferCreatePayload; narrows the types
    // for the confirmation text below.
    if (!sourceAccount || !destinationAccount) {
      return;
    }

    const { payload } = result;

    // The local-date comparison only chooses the wording; the server
    // classifies planned vs posted with its own date (D13 known gap).
    const outcome =
      payload.transfer_date > localToday
        ? "The date is in the future, so it will be saved as planned and " +
          "will not change any balance until you post it."
        : "It will be posted immediately and update both balances.";

    Alert.alert(
      "Create transfer?",
      `${payload.amount} ${sourceAccount.currency} from ` +
        `${sourceAccount.name} to ${destinationAccount.name} ` +
        `on ${payload.transfer_date}.\n\n${outcome}`,
      [
        { text: "Cancel", style: "cancel" },
        { text: "Create", onPress: () => submitPayload(payload) },
      ],
    );
  }

  if (isAccountsLoading) {
    return (
      <SafeAreaView style={styles.container}>
        <ActivityIndicator style={styles.loader} />
      </SafeAreaView>
    );
  }

  // Without any Account data there is nothing to transfer between. When a
  // refetch fails but cached Accounts exist, the form stays usable and
  // shows a notice instead (see below).
  if (!accounts) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.content}>
          <Text style={styles.errorText}>
            {accountsError
              ? "Unable to load accounts. A transfer needs your accounts."
              : "Accounts are not available."}
          </Text>
        </View>
      </SafeAreaView>
    );
  }

  if (activeAccounts.length < 2) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.content}>
          <Text style={styles.secondaryText}>
            You need at least two active accounts to create a transfer.
          </Text>
        </View>
      </SafeAreaView>
    );
  }

  if (!hasSameCurrencyPair(activeAccounts)) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.content}>
          <Text style={styles.secondaryText}>
            Transfers currently require two active accounts in the same
            currency.
          </Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <KeyboardAvoidingView
        style={styles.container}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <ScrollView
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
        >
          <Text style={styles.title}>New transfer</Text>

          <Text style={styles.helperText}>* Required fields</Text>

          {accountsError ? (
            <Text style={styles.noticeText}>
              Unable to refresh accounts. The list below may be out of date.
            </Text>
          ) : null}

          <View style={styles.formGroup}>
            <Text style={styles.label}>Source account *</Text>

            <TransferAccountPicker
              options={activeAccounts}
              selectedAccountId={sourceAccountId}
              onChange={handleSourceChange}
              title="Transfer from"
              placeholder="Select source account"
            />
          </View>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Destination account *</Text>

            <TransferAccountPicker
              options={destinationOptions}
              selectedAccountId={destinationAccountId}
              onChange={setDestinationAccountId}
              title="Transfer to"
              placeholder={
                sourceAccount
                  ? "Select destination account"
                  : "Select a source account first"
              }
              disabled={!sourceAccount || destinationOptions.length === 0}
            />

            {sourceAccount && destinationOptions.length === 0 ? (
              <Text style={styles.helperText}>
                No other active account uses {sourceAccount.currency}.
              </Text>
            ) : null}
          </View>

          {sourceAccount ? (
            <Text style={styles.helperText}>
              Currency: {sourceAccount.currency} (set by the accounts; both
              must use the same currency)
            </Text>
          ) : null}

          <View style={styles.formGroup}>
            <Text style={styles.label}>Amount *</Text>

            <TextInput
              style={styles.input}
              placeholder="0.00"
              value={amount}
              onChangeText={setAmount}
              keyboardType="decimal-pad"
            />
          </View>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Transfer date *</Text>

            <TextInput
              style={styles.input}
              placeholder="YYYY-MM-DD"
              value={transferDate}
              onChangeText={setTransferDate}
            />

            {hasDateShape ? (
              <Text style={styles.helperText}>
                {trimmedTransferDate > localToday
                  ? "Future date: will be planned. It will not change any " +
                    "balance until you post it."
                  : "Today or earlier: will be posted immediately."}
              </Text>
            ) : null}
          </View>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Description</Text>

            <TextInput
              style={[styles.input, styles.inputOptional]}
              placeholder="Optional note"
              value={description}
              onChangeText={setDescription}
              maxLength={500}
            />
          </View>

          <Pressable
            disabled={createTransferMutation.isPending}
            onPress={handleCreateTransfer}
            style={[styles.button, styles.formGroup]}
          >
            {createTransferMutation.isPending ? (
              <ActivityIndicator />
            ) : (
              <Text style={styles.buttonText}>Save transfer</Text>
            )}
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
