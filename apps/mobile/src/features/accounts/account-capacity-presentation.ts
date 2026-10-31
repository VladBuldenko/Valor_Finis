// What the Account screen shows for the reservation and rule read model
// (VF-020F2, M09). Every value is the backend's decimal string rendered as
// returned with the Account's OWN currency: no parsing, no arithmetic, no
// rounding and no cross-Account total.
import type { Account } from "./account.types";

export type CapacityRow = {
  id: "reservable" | "floor" | "holds" | "rule_capacity";
  label: string;
  value: string;
  // Read by screen readers instead of the visible pair.
  accessibilityLabel: string;
  // One short sentence that stops the figure being misread.
  note: string;
  // True for a negative amount; shown as returned, never as zero.
  isNegative: boolean;
};

// A string test only: "-12.50" is negative, "-0.00" and "0.00" are not.
export function isNegativeDecimalString(value: string): boolean {
  return /^-/.test(value) && /[1-9]/.test(value);
}

function row(
  id: CapacityRow["id"],
  label: string,
  rawValue: string,
  currency: string,
  note: string,
): CapacityRow {
  const value = `${rawValue} ${currency}`;
  const isNegative = isNegativeDecimalString(rawValue);

  return {
    id,
    label,
    value,
    accessibilityLabel: `${label}: ${value}${isNegative ? ", below zero" : ""}. ${note}`,
    note,
    isNegative,
  };
}

export function getAccountCapacityRows(
  account: Pick<
    Account,
    | "currency"
    | "reservable_amount"
    | "minimum_unallocated_floor"
    | "active_rule_holds"
    | "rule_capacity"
  >,
): CapacityRow[] {
  const { currency } = account;

  return [
    row(
      "reservable",
      "Available to reserve",
      account.reservable_amount,
      currency,
      "Money in this Account that Goals can still earmark.",
    ),
    row(
      "floor",
      "Minimum unallocated floor",
      account.minimum_unallocated_floor,
      currency,
      "A threshold you set. It does not remove money from the Account.",
    ),
    row(
      "holds",
      "Active rule holds",
      account.active_rule_holds,
      currency,
      "Suggestions waiting for your confirmation. A hold is not a completed reservation.",
    ),
    row(
      "rule_capacity",
      "Available for rules",
      account.rule_capacity,
      currency,
      "What rules may use. It can be below zero.",
    ),
  ];
}

export const CAPACITY_SECTION_TITLE = "Rules and the minimum floor";

export const CAPACITY_FOOTNOTE =
  "Earmarking money for a Goal does not change this Account's balance or move money anywhere.";

export const NEGATIVE_CAPACITY_HINT =
  "Below zero: the floor and holds together are more than is available to reserve.";
