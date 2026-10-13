// Focused tests for goal-partitions.ts (VF-020C3): partition options,
// contribution Account options, labels and the exact-string money checks.
//   node --experimental-strip-types --test src/features/goals/goal-partitions.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ACCOUNT_UNAVAILABLE_LABEL,
  buildContributionAccountOptions,
  buildWithdrawalPartitionOptions,
  getAccountDisplayName,
  getGoalTransactionKindLabel,
  isNonPositiveMoney,
  isZeroMoney,
  TRACKED_PARTITION_KEY,
} from "./goal-partitions.ts";

const A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";

function account(id, overrides = {}) {
  return {
    id,
    name: `Account ${id.slice(0, 1)}`,
    status: "active",
    currency: "EUR",
    reservable_amount: "100.00",
    ...overrides,
  };
}

test("exact-string money checks", () => {
  assert.equal(isZeroMoney("0.00"), true);
  assert.equal(isZeroMoney("0"), true);
  assert.equal(isZeroMoney("-0.00"), true);
  assert.equal(isZeroMoney("0.01"), false);
  assert.equal(isZeroMoney("10.00"), false);
  assert.equal(isZeroMoney("100.00"), false);
  assert.equal(isNonPositiveMoney("-5.00"), true);
  assert.equal(isNonPositiveMoney("0.00"), true);
  assert.equal(isNonPositiveMoney("0.01"), false);
});

test("tracked partition with a non-zero amount appears, zero is hidden", () => {
  const shown = buildWithdrawalPartitionOptions({ tracked_amount: "30.00", allocations: [] }, []);
  const hidden = buildWithdrawalPartitionOptions({ tracked_amount: "0.00", allocations: [] }, []);

  assert.equal(shown.length, 1);
  assert.equal(shown[0].key, TRACKED_PARTITION_KEY);
  assert.equal(shown[0].accountId, null);
  assert.equal(shown[0].amount, "30.00");
  assert.deepEqual(hidden, []);
});

test("linked allocations appear with the exact account_id and a zero one is absent", () => {
  const options = buildWithdrawalPartitionOptions(
    {
      tracked_amount: "0.00",
      allocations: [
        { account_id: A, amount: "40.00" },
        { account_id: B, amount: "0.00" },
      ],
    },
    [account(A), account(B)],
  );

  assert.equal(options.length, 1);
  assert.equal(options[0].accountId, A);
  assert.equal(options[0].amount, "40.00");
  assert.equal(options[0].label, "Account a");
});

test("an archived Account's partition stays releasable and is labelled", () => {
  const options = buildWithdrawalPartitionOptions(
    { tracked_amount: "0.00", allocations: [{ account_id: A, amount: "40.00" }] },
    [account(A, { status: "archived" })],
  );

  assert.equal(options.length, 1);
  assert.equal(options[0].accountId, A);
  assert.equal(options[0].label, "Account a (archived)");
});

test("an unresolved Account keeps its partition selectable with the fallback label", () => {
  const options = buildWithdrawalPartitionOptions(
    { tracked_amount: "0.00", allocations: [{ account_id: C, amount: "5.00" }] },
    [],
  );

  assert.equal(options.length, 1);
  assert.equal(options[0].accountId, C);
  assert.equal(options[0].label, ACCOUNT_UNAVAILABLE_LABEL);
  assert.equal(getAccountDisplayName(C, []), ACCOUNT_UNAVAILABLE_LABEL);
});

test("options carry no selection of their own: nothing is preselected or merged", () => {
  const options = buildWithdrawalPartitionOptions(
    {
      tracked_amount: "10.00",
      allocations: [{ account_id: A, amount: "20.00" }, { account_id: B, amount: "30.00" }],
    },
    [account(A), account(B)],
  );

  assert.equal(options.length, 3);
  assert.deepEqual(options.map((option) => option.accountId), [null, A, B]);
  for (const option of options) {
    assert.equal("selected" in option, false);
  }
  assert.equal(new Set(options.map((option) => option.key)).size, 3);
});

test("a single partition is still an option the user must pick (no auto-selection data)", () => {
  const options = buildWithdrawalPartitionOptions({ tracked_amount: "10.00", allocations: [] }, []);

  assert.equal(options.length, 1);
  assert.equal("selected" in options[0], false);
});

test("contribution Account options: active and same currency only", () => {
  const options = buildContributionAccountOptions(
    [
      account(A),
      account(B, { status: "archived" }),
      account(C, { currency: "USD" }),
    ],
    "EUR",
  );

  assert.deepEqual(options.map((option) => option.accountId), [A]);
  assert.equal(options[0].label, "Account a — EUR");
  assert.equal(options[0].reservableAmount, "100.00");
  assert.equal(options[0].hasNoCapacity, false);
});

test("archived and other-currency Accounts are never offered for a new reservation", () => {
  const options = buildContributionAccountOptions(
    [account(A, { status: "archived" }), account(B, { currency: "USD" })],
    "EUR",
  );

  assert.deepEqual(options, []);
});

test("zero or negative capacity is a hint, not an exclusion", () => {
  const options = buildContributionAccountOptions(
    [account(A, { reservable_amount: "0.00" }), account(B, { reservable_amount: "-25.00" })],
    "EUR",
  );

  assert.equal(options.length, 2);
  assert.deepEqual(options.map((option) => option.hasNoCapacity), [true, true]);
});

test("history labels: tracked vs linked rows", () => {
  assert.equal(getGoalTransactionKindLabel({ type: "contribution", account_id: null }), "Contribution");
  assert.equal(getGoalTransactionKindLabel({ type: "withdrawal", account_id: null }), "Withdrawal");
  assert.equal(getGoalTransactionKindLabel({ type: "contribution", account_id: A }), "Reservation");
  assert.equal(getGoalTransactionKindLabel({ type: "withdrawal", account_id: A }), "Release");
  assert.equal(getGoalTransactionKindLabel({ type: "opening_balance", account_id: null }), "Opening balance");
});
