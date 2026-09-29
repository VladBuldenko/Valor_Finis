import { Link } from "expo-router";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { getApiErrorMessage } from "../../api/api-error-message";
import { getAccounts } from "../accounts/account.service";
import type { Account } from "../accounts/account.types";
import { useAuth } from "../auth/auth-context";
import { formatLocalCalendarDate } from "./local-calendar-date";
import { invalidateTransferQueries } from "./transfer-cache";
import {
  deleteAccountTransfer,
  getAccountTransfers,
  postAccountTransfer,
} from "./transfer.service";
import type { AccountTransfer, AccountTransferStatus } from "./transfer.types";
import { styles } from "./transfers.styles";

const STATUS_LABELS: Record<AccountTransferStatus, string> = {
  planned: "Planned",
  posted: "Posted",
};

// Presentation-only label for one side of a transfer, resolved from the
// shared ["accounts", userId] list (active AND archived, so a transfer
// involving a since-archived Account still shows its name). A raw Account
// id is never shown: while Accounts load the label stays neutral, and an id
// the list cannot resolve gets "Account unavailable".
function getAccountLabel(
  accountId: string,
  accountsById: Map<string, Account>,
  isAccountsLoading: boolean,
): string {
  if (isAccountsLoading) {
    return "Account";
  }

  const account = accountsById.get(accountId);

  if (!account) {
    return "Account unavailable";
  }

  return account.status === "archived"
    ? `${account.name} (archived)`
    : account.name;
}

export function TransfersScreen() {
  const { session } = useAuth();
  const queryClient = useQueryClient();

  const {
    data: transfers = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["account-transfers", session?.user.id],
    queryFn: getAccountTransfers,
    enabled: Boolean(session),
  });

  // Supplementary data used only for Account names and the "Blocked"
  // badge. Transfers are the canonical list here, so a failure of this
  // query never hides them -- it shows a small notice and neutral labels.
  const {
    data: accounts = [],
    isLoading: isAccountsLoading,
    error: accountsError,
  } = useQuery({
    queryKey: ["accounts", session?.user.id],
    queryFn: getAccounts,
    enabled: Boolean(session),
  });

  const accountsById = new Map<string, Account>(
    accounts.map((account) => [account.id, account]),
  );

  // Local calendar date, used only for the presentation-only "Due" badge.
  const localToday = formatLocalCalendarDate(new Date());

  const postTransferMutation = useMutation({
    mutationFn: (variables: { transferId: string; effectiveDate: string }) =>
      postAccountTransfer(variables.transferId, {
        effective_date: variables.effectiveDate,
      }),

    // Posting creates both ledger rows: balances and both histories are
    // refetched from the backend, never adjusted locally.
    onSuccess: async () => {
      await invalidateTransferQueries(queryClient, session?.user.id, true);
    },

    // e.g. 409 already posted (another device posted it), 409 archived
    // Account, 422 effective date in the future for the server (D13), 404.
    // The list is refetched afterwards so it shows the current state --
    // including balances, in case the transfer was posted elsewhere.
    onError: async (mutationError) => {
      Alert.alert(
        "Post transfer failed",
        getApiErrorMessage(mutationError, "Unable to post transfer."),
      );

      await invalidateTransferQueries(queryClient, session?.user.id, true);
    },
  });

  const deleteTransferMutation = useMutation({
    mutationFn: (transferId: string) => deleteAccountTransfer(transferId),

    // Always treated as touching the ledger: a transfer shown as planned
    // may have been posted elsewhere, and deleting a posted transfer
    // removes both of its ledger rows on the backend.
    onSuccess: async () => {
      await invalidateTransferQueries(queryClient, session?.user.id, true);
    },

    onError: (mutationError) => {
      Alert.alert(
        "Delete transfer failed",
        getApiErrorMessage(mutationError, "Unable to delete transfer."),
      );
    },
  });

  function handlePostTransfer(transfer: AccountTransfer) {
    // Guards against duplicate submissions while a post is in flight.
    if (postTransferMutation.isPending) {
      return;
    }

    // Always an explicit effective_date: the user's local calendar date,
    // resolved when the dialog opens, is exactly the date they confirm.
    const effectiveDate = formatLocalCalendarDate(new Date());

    Alert.alert(
      "Post transfer?",
      `This records ${transfer.amount} ${transfer.currency} as moved on ` +
        `${effectiveDate} and updates both account balances. Posting ` +
        "cannot be undone -- only deleted.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Post",
          onPress: () =>
            postTransferMutation.mutate({
              transferId: transfer.id,
              effectiveDate,
            }),
        },
      ],
    );
  }

  function handleDeleteTransfer(transfer: AccountTransfer) {
    if (deleteTransferMutation.isPending) {
      return;
    }

    Alert.alert(
      "Delete transfer?",
      transfer.status === "posted"
        ? "This transfer will be permanently deleted and removed from both " +
            "accounts' history; both balances return to their previous values."
        : "This planned transfer will be permanently deleted.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: () => deleteTransferMutation.mutate(transfer.id),
        },
      ],
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title}>Transfers</Text>

        <Link href="/transfers/new" asChild>
          <Pressable style={styles.button}>
            <Text style={styles.buttonText}>New transfer</Text>
          </Pressable>
        </Link>

        {accountsError ? (
          <Text style={styles.noticeText}>
            Account names are unavailable right now.
          </Text>
        ) : null}

        {isLoading ? (
          <ActivityIndicator style={styles.loader} />
        ) : error ? (
          <Text style={styles.errorText}>Unable to load transfers.</Text>
        ) : transfers.length === 0 ? (
          <Text style={styles.secondaryText}>No transfers yet.</Text>
        ) : (
          <View style={styles.list}>
            {/* Backend order, never re-sorted here. */}
            {transfers.map((transfer) => {
              const isPlanned = transfer.status === "planned";
              const sourceAccount = accountsById.get(
                transfer.source_account_id,
              );
              const destinationAccount = accountsById.get(
                transfer.destination_account_id,
              );

              // Presentation hints only; transfer.status stays the
              // authority and the backend decides whether a post succeeds.
              const isDue =
                isPlanned &&
                transfer.planned_date !== null &&
                transfer.planned_date <= localToday;
              const isBlocked =
                isPlanned &&
                (sourceAccount?.status === "archived" ||
                  destinationAccount?.status === "archived");

              const isPosting =
                postTransferMutation.isPending &&
                postTransferMutation.variables?.transferId === transfer.id;
              const isDeleting =
                deleteTransferMutation.isPending &&
                deleteTransferMutation.variables === transfer.id;

              return (
                <View key={transfer.id} style={styles.card}>
                  <Text style={styles.name}>
                    From:{" "}
                    {getAccountLabel(
                      transfer.source_account_id,
                      accountsById,
                      isAccountsLoading,
                    )}
                  </Text>

                  <Text style={styles.name}>
                    To:{" "}
                    {getAccountLabel(
                      transfer.destination_account_id,
                      accountsById,
                      isAccountsLoading,
                    )}
                  </Text>

                  <Text style={styles.amount}>
                    {transfer.amount} {transfer.currency}
                  </Text>

                  <View style={styles.statusRow}>
                    <Text style={styles.statusText}>
                      {STATUS_LABELS[transfer.status]}
                    </Text>

                    {isDue ? (
                      <View style={styles.badge}>
                        <Text style={styles.badgeText}>Due</Text>
                      </View>
                    ) : null}

                    {isBlocked ? (
                      <View style={styles.badge}>
                        <Text style={styles.badgeText}>Blocked</Text>
                      </View>
                    ) : null}
                  </View>

                  {transfer.planned_date !== null ? (
                    <Text style={styles.secondaryText}>
                      Planned: {transfer.planned_date}
                    </Text>
                  ) : null}

                  {transfer.effective_date !== null ? (
                    <Text style={styles.secondaryText}>
                      Effective: {transfer.effective_date}
                    </Text>
                  ) : null}

                  {transfer.description ? (
                    <Text style={styles.secondaryText}>
                      {transfer.description}
                    </Text>
                  ) : null}

                  {isBlocked ? (
                    <Text style={styles.noticeText}>
                      An account of this transfer is archived. Reactivate it
                      to post, or delete this transfer.
                    </Text>
                  ) : null}

                  <View style={styles.actionRow}>
                    {isPlanned ? (
                      <Pressable
                        style={styles.actionButton}
                        disabled={postTransferMutation.isPending}
                        onPress={() => handlePostTransfer(transfer)}
                      >
                        {isPosting ? (
                          <ActivityIndicator size="small" />
                        ) : (
                          <Text style={styles.actionButtonText}>
                            Post transfer
                          </Text>
                        )}
                      </Pressable>
                    ) : null}

                    <Pressable
                      style={styles.deleteButton}
                      disabled={deleteTransferMutation.isPending}
                      onPress={() => handleDeleteTransfer(transfer)}
                    >
                      {isDeleting ? (
                        <ActivityIndicator size="small" />
                      ) : (
                        <Text style={styles.deleteButtonText}>
                          Delete transfer
                        </Text>
                      )}
                    </Pressable>
                  </View>
                </View>
              );
            })}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
