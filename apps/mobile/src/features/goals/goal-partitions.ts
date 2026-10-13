import type { Account } from "../accounts/account.types";
import type { Goal, GoalTransaction } from "./goal.types";

// Pure presentation helpers for Account-linked Goal operations (VF-020C3).
// Nothing here parses or adds money: amounts are the backend's JSON strings
// and the only comparisons are exact string checks on the backend's
// canonical decimal form. The backend stays the authority on every rule.

// Display fallback for an Account id the cached Account list cannot resolve.
export const ACCOUNT_UNAVAILABLE_LABEL = "Account unavailable";

// Returns whether a backend decimal string is exactly zero ("0", "0.00",
// "-0.00"). String-safe: no Number/parseFloat.
export function isZeroMoney(amount: string): boolean {
  return /^-?0+(\.0+)?$/.test(amount.trim());
}

// Returns whether a backend decimal string is zero or negative. Used only
// for the non-blocking "No capacity" hint, never to disable a submit.
export function isNonPositiveMoney(amount: string): boolean {
  const trimmed = amount.trim();

  return trimmed.startsWith("-") || isZeroMoney(trimmed);
}

// Returns the display name of an Account id from the cached Account list:
// "<name>", "<name> (archived)", or "Account unavailable" when the id is not
// in the list. Never throws and never needs a per-Account request.
export function getAccountDisplayName(
  accountId: string,
  accounts: readonly Pick<Account, "id" | "name" | "status">[],
): string {
  const account = accounts.find((candidate) => candidate.id === accountId);

  if (!account) {
    return ACCOUNT_UNAVAILABLE_LABEL;
  }

  return account.status === "archived" ? `${account.name} (archived)` : account.name;
}

// One selectable Account for a NEW reservation.
export type ContributionAccountOption = {
  accountId: string;
  label: string;
  reservableAmount: string;
  currency: string;
  hasNoCapacity: boolean;
};

// Accounts a NEW linked contribution may target: ACTIVE and in the Goal's
// currency only (no FX). Archived and other-currency Accounts are excluded.
// This is UX filtering only; the backend re-validates ownership, lifecycle,
// currency and capacity.
export function buildContributionAccountOptions(
  accounts: readonly Account[],
  goalCurrency: string,
): ContributionAccountOption[] {
  return accounts
    .filter(
      (account) =>
        account.status === "active" && account.currency === goalCurrency,
    )
    .map((account) => ({
      accountId: account.id,
      label: `${account.name} — ${account.currency}`,
      reservableAmount: account.reservable_amount,
      currency: account.currency,
      hasNoCapacity: isNonPositiveMoney(account.reservable_amount),
    }));
}

// One selectable withdrawal partition. accountId null = the tracked
// partition; otherwise the Goal's partition linked to that Account.
export type WithdrawalPartitionOption = {
  key: string;
  accountId: string | null;
  label: string;
  amount: string;
};

export const TRACKED_PARTITION_KEY = "tracked";

// Partitions a withdrawal may be taken from, built ONLY from the Goal's own
// read model: the tracked partition (when its amount is not zero) and every
// current linked allocation. An allocation is never hidden because its
// Account is archived or unresolved - it must stay releasable. Nothing is
// preselected, merged, ordered by size or used as a fallback for another.
export function buildWithdrawalPartitionOptions(
  goal: Pick<Goal, "tracked_amount" | "allocations">,
  accounts: readonly Pick<Account, "id" | "name" | "status">[],
): WithdrawalPartitionOption[] {
  const options: WithdrawalPartitionOption[] = [];

  if (!isZeroMoney(goal.tracked_amount)) {
    options.push({
      key: TRACKED_PARTITION_KEY,
      accountId: null,
      label: "Tracked (not tied to an account)",
      amount: goal.tracked_amount,
    });
  }

  for (const allocation of goal.allocations) {
    if (isZeroMoney(allocation.amount)) {
      continue;
    }

    options.push({
      key: `account:${allocation.account_id}`,
      accountId: allocation.account_id,
      label: getAccountDisplayName(allocation.account_id, accounts),
      amount: allocation.amount,
    });
  }

  return options;
}

// Returns the history label of a Goal transaction: linked rows read as
// Reservation / Release, tracked rows keep Contribution / Withdrawal, and an
// opening balance is always an opening balance.
export function getGoalTransactionKindLabel(
  transaction: Pick<GoalTransaction, "type" | "account_id">,
): string {
  if (transaction.type === "opening_balance") {
    return "Opening balance";
  }

  if (transaction.account_id !== null) {
    return transaction.type === "withdrawal" ? "Release" : "Reservation";
  }

  return transaction.type === "withdrawal" ? "Withdrawal" : "Contribution";
}
