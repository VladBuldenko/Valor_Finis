import { Link } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import {
  Pressable,
  RefreshControl,
  ScrollView,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { PagedListFooter } from "../../components/paged-list-footer";
import { InlineError, QueryBoundary } from "../../components/query-states";
import { PAGED_COPY } from "../../lib/paged-list";
import { refetcherOf, useScreenRefresh } from "../../lib/screen-refresh";
import { usePagedList } from "../../lib/use-paged-list";
import { useAuth } from "../auth/auth-context";
import { getAccounts } from "../accounts/account.service";
import type { Account } from "../accounts/account.types";
import { incomeKeys } from "./income-query-keys";
import { getIncomePage } from "./income.service";
import { styles } from "./income.styles";
import { INCOME_SOURCE_LABELS, type Income } from "./income.types";

// Presentation-only label for an Income's linked Account. Uses the shared
// ["accounts", userId] list (active and archived) purely to show a name --
// never to compute or display a balance. A raw account_id is never shown:
// while Accounts are still loading the label stays neutral, and an id the
// list cannot resolve gets "Linked account unavailable".
function getLinkedAccountLabel(
  income: Income,
  accounts: Account[],
  isAccountsLoading: boolean,
): string | null {
  if (income.account_id === null) {
    return null;
  }

  if (isAccountsLoading) {
    return "Linked account";
  }

  const account = accounts.find(
    (candidate) => candidate.id === income.account_id,
  );

  if (!account) {
    return "Linked account unavailable";
  }

  return account.status === "archived"
    ? `Account: ${account.name} (archived)`
    : `Account: ${account.name}`;
}

export function IncomeScreen() {
  const { session } = useAuth();

  // The list is read one page at a time (VF-MVP-BETA-001). The rows already
  // loaded stay on screen while later pages load or fail; a refresh re-reads
  // the pages already loaded.
  const incomeList = usePagedList<Income>({
    queryKey: session ? incomeKeys.list(session.user.id) : null,
    fetchPage: getIncomePage,
  });
  const incomeFeed = incomeList.feed;

  // Same query key/data as the Accounts screen, so an Account rename or
  // archive is reflected here without a separate fetch path.
  const accountsQuery = useQuery({
    queryKey: ["accounts", session?.user.id],
    queryFn: getAccounts,
    enabled: Boolean(session),
  });
  const accounts = accountsQuery.data ?? [];
  // A failed Accounts read must not turn into "Linked account unavailable".
  const accountNamesUnknown = accountsQuery.data === undefined;
  const refresh = useScreenRefresh(() => [refetcherOf(incomeFeed), refetcherOf(accountsQuery)]);

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refresh.refreshing} onRefresh={refresh.onRefresh} />}
      >
        <Text style={styles.title}>Income</Text>

        <Link href="/income/new" asChild>
          <Pressable style={styles.button}>
            <Text style={styles.buttonText}>Add income</Text>
          </Pressable>
        </Link>

        {accountsQuery.isError && accountNamesUnknown ? (
          <InlineError
            what="account names"
            error={accountsQuery.error}
            kind="partial"
            retrying={accountsQuery.isFetching}
            onRetry={() => void accountsQuery.refetch()}
          />
        ) : null}

        <QueryBoundary
          query={{
            data: incomeList.merged ?? undefined,
            error: incomeFeed.error,
            // A failed LATER page is reported by the footer, below the rows.
            isError: incomeFeed.isError && !incomeFeed.isFetchNextPageError,
            isFetching: incomeFeed.isFetching,
            refetch: incomeFeed.refetch,
          }}
          what="income"
          empty="No income yet."
          isEmpty={(list) => list.items.length === 0}
        >
          {(list) => (
          <>
          <View style={styles.list}>
            {list.items.map((income) => {
              const linkedAccountLabel = getLinkedAccountLabel(
                income,
                accounts,
                accountNamesUnknown,
              );

              return (
                <View key={income.id} style={styles.card}>
                  <Text style={styles.name}>
                    {INCOME_SOURCE_LABELS[income.source]}
                  </Text>

                  <Text style={styles.amount}>
                    {income.amount} {income.currency}
                  </Text>

                  <Text style={styles.secondaryText}>{income.received_at}</Text>

                  {income.description ? (
                    <Text style={styles.secondaryText}>
                      {income.description}
                    </Text>
                  ) : null}

                  {linkedAccountLabel ? (
                    <Text style={styles.secondaryText}>
                      {linkedAccountLabel}
                    </Text>
                  ) : null}

                  <Link
                    href={{
                      pathname: "/income/[id]/edit",
                      params: { id: income.id },
                    }}
                    asChild
                  >
                    <Pressable style={styles.editButton}>
                      <Text style={styles.editButtonText}>Edit income</Text>
                    </Pressable>
                  </Link>
                </View>
              );
            })}
          </View>

          <PagedListFooter
            state={incomeList.state}
            merged={incomeList.merged}
            what="income"
            error={incomeFeed.error}
            onLoadMore={() => void incomeFeed.fetchNextPage()}
            buttonStyle={styles.button}
            buttonTextStyle={styles.buttonText}
            noteStyle={styles.secondaryText}
          />
          <Text style={styles.secondaryText}>{PAGED_COPY.paging}</Text>
          </>
          )}
        </QueryBoundary>
      </ScrollView>
    </SafeAreaView>
  );
}
