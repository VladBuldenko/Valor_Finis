// Receipt confirmation cache handling (VF-MVP-CORE-005) with a real TanStack QueryClient: exactly which
// query families are refreshed after a confirmation, and how a FAILED confirmation is reconciled by
// rereading the receipt (the write itself is never resent).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { QueryClient } from "@tanstack/react-query";

import {
  invalidateConfirmedReceiptQueries,
  receiptDetailKey,
  recoverFailedConfirmation,
} from "./receipt-confirm-recovery.ts";
import type { Receipt } from "./receipt.types.ts";

const USER = "user-1";

const KEYS = {
  receipts: ["receipts", USER],
  detail: ["receipts", "detail", "r-1"],
  expenses: ["expenses", USER],
  accounts: ["accounts", USER],
  accountHistory: ["accounts", "transactions", USER, "acc-1"],
  budgetStatus: ["analytics", "budget-status", USER],
  overview: ["analytics", "financial-overview", USER, 2026, 11],
  monthlySummary: ["analytics", "monthly-summary", USER, 2026, 11],
  income: ["income", USER],
  goals: ["goals", USER],
  transfers: ["account-transfers", USER],
  otherUsersExpenses: ["expenses", "user-2"],
};

function seeded() {
  const client = new QueryClient();

  for (const key of Object.values(KEYS)) {
    client.setQueryData(key, []);
  }

  return client;
}

function invalidated(client: QueryClient): string[] {
  return Object.entries(KEYS)
    .filter(([, key]) => client.getQueryState(key)?.isInvalidated)
    .map(([name]) => name)
    .sort();
}

function receipt(overrides: Partial<Receipt>): Receipt {
  return {
    id: "r-1",
    user_id: USER,
    expense_id: null,
    file_url: null,
    storage_path: "p",
    status: "processed",
    ocr_text: null,
    merchant_detected: null,
    total_amount_detected: null,
    currency_detected: null,
    purchase_date_detected: null,
    created_at: "2026-11-11T10:00:00Z",
    updated_at: "2026-11-11T10:00:00Z",
    ...overrides,
  };
}

const EXPENSE_SET = ["budgetStatus", "expenses", "monthlySummary", "overview"];

describe("invalidateConfirmedReceiptQueries", () => {
  it("an unlinked confirmation refreshes receipts and the Expense/analytics set, never Accounts", async () => {
    const client = seeded();

    await invalidateConfirmedReceiptQueries(client, USER, false);

    assert.deepEqual(invalidated(client), ["detail", "receipts", ...EXPENSE_SET].sort());
  });

  it("a linked confirmation also refreshes the Account list and every Account history", async () => {
    const client = seeded();

    await invalidateConfirmedReceiptQueries(client, USER, true);

    assert.deepEqual(invalidated(client), ["accountHistory", "accounts", "detail", "receipts", ...EXPENSE_SET].sort());
  });

  it("never refreshes Income, Goals or Transfers, nor another user's cache", async () => {
    const client = seeded();

    await invalidateConfirmedReceiptQueries(client, USER, true);

    for (const untouched of ["income", "goals", "transfers", "otherUsersExpenses"]) {
      assert.equal(client.getQueryState(KEYS[untouched as keyof typeof KEYS])?.isInvalidated, false, untouched);
    }
  });
});

describe("recoverFailedConfirmation (the confirm request failed; was it committed?)", () => {
  it("a receipt that reads confirmed means the Expense exists: caches are refreshed and its id is returned", async () => {
    const client = seeded();
    const confirmed = receipt({ status: "confirmed", expense_id: "e-1" });

    const result = await recoverFailedConfirmation(client, USER, "r-1", async () => confirmed);

    assert.deepEqual(result, { confirmed: true, expenseId: "e-1" });
    assert.deepEqual(client.getQueryData(receiptDetailKey("r-1")), confirmed, "the screen switches to the confirmed branch");
    assert.deepEqual(invalidated(client), ["accountHistory", "accounts", "detail", "receipts", ...EXPENSE_SET].sort());
  });

  it("a receipt that is still processed means nothing was written: no Expense or Account cache is refreshed", async () => {
    const client = seeded();
    const processed = receipt({ status: "processed" });

    const result = await recoverFailedConfirmation(client, USER, "r-1", async () => processed);

    assert.deepEqual(result, { confirmed: false, expenseId: null });
    assert.deepEqual(client.getQueryData(receiptDetailKey("r-1")), processed, "the form stays");
    assert.deepEqual(invalidated(client), []);
  });

  it("when the reread itself fails nothing is assumed: no throw, no Expense refresh, the detail query refetches", async () => {
    const client = seeded();

    const result = await recoverFailedConfirmation(client, USER, "r-1", async () => {
      throw new TypeError("Network request failed");
    });

    assert.deepEqual(result, { confirmed: false, expenseId: null });
    assert.deepEqual(invalidated(client), ["detail"]);
  });

  it("asks for exactly the receipt that failed, once", async () => {
    const asked: string[] = [];

    await recoverFailedConfirmation(seeded(), USER, "r-1", async (id) => {
      asked.push(id);

      return receipt({ status: "processed" });
    });

    assert.deepEqual(asked, ["r-1"]);
  });
});

describe("stale sessions", () => {
  it("only ever writes to the client it was given, never to another session's cache", async () => {
    const oldSession = seeded();
    const newSession = seeded();
    const confirmed = receipt({ status: "confirmed", expense_id: "e-1" });

    await recoverFailedConfirmation(oldSession, USER, "r-1", async () => confirmed);

    assert.deepEqual(invalidated(newSession), []);
    assert.equal(newSession.getQueryData(receiptDetailKey("r-1")) instanceof Array, true, "the new session's cache is untouched");
  });

  it("the review screen drops the result of a confirmation that finished after the user changed (static source check)", () => {
    const source = readFileSync(new URL("./receipt-review-screen.tsx", import.meta.url), "utf8");
    const recovered = source.indexOf("await recoverFailedConfirmation(");
    const alertAfterRecovery = source.indexOf("Alert.alert(", recovered);
    const guard = source.indexOf("isCurrentQueryClient(queryClient)", recovered);
    const navigation = source.indexOf("router.replace(");
    const successGuard = source.lastIndexOf("isCurrentQueryClient(queryClient)", navigation);

    assert.ok(recovered > 0 && guard > recovered && guard < alertAfterRecovery, "no alert before the session check");
    assert.ok(successGuard > 0 && successGuard < navigation, "no navigation before the session check");
  });
});
