// Structural guards for the Income / Expense create screens (VF-MVP-CORE-002):
// they cannot be mounted by the Node runner, so the wiring is checked against the
// source. These fail if a screen sends a create without a key, stops keeping the
// key across a failure, or stops guarding double taps.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { stripComments } from "./financial-rules/financial-rule-forbidden-copy.ts";

const code = (path: string) => stripComments(readFileSync(path, "utf8"));

const SCREENS = [
  { name: "income", path: "src/features/income/income-create-screen.tsx", mutation: "createIncomeMutation", toInput: "toIncomeCreateInput" },
  { name: "expense", path: "src/features/expenses/expenses-screen.tsx", mutation: "createExpenseMutation", toInput: "toExpenseCreateInput" },
] as const;

for (const screen of SCREENS) {
  describe(`${screen.name} create screen`, () => {
    const source = code(screen.path);

    it("sends every create through the attempt resolver, never a bare payload", () => {
      assert.match(source, /resolveCreateAttempt\(/);
      assert.match(source, new RegExp(`${screen.mutation}\\.mutate\\(${screen.toInput}\\(attempt\\)\\)`));
      assert.doesNotMatch(source, new RegExp(`${screen.mutation}\\.mutate\\(payload\\)`));
    });

    it("generates ids with expo-crypto randomUUID only inside the resolver call", () => {
      assert.match(source, /Crypto\.randomUUID\(\)/);
      assert.equal((source.match(/randomUUID/g) ?? []).length, 1);
    });

    it("keeps the attempts on failure and clears them only after a success or a rejected key", () => {
      const onSuccess = source.slice(source.indexOf("onSuccess"), source.indexOf("onError"));
      const onError = source.slice(source.indexOf("onError"), source.indexOf("onSettled"));

      assert.match(onSuccess, /createAttemptsRef\.current = \[\]/);
      assert.match(onError, /failure\.discardAttempt/);
      assert.equal((onError.match(/createAttemptsRef\.current = \[\]/g) ?? []).length, 1);
    });

    it("guards double taps synchronously and releases the guard when the request settles", () => {
      assert.match(source, /createSubmitGuard\(\)/);
      assert.match(source, /submitGuardRef\.current\.tryEnter\(\)/);
      assert.match(source, /onSettled:[\s\S]*submitGuardRef\.current\.release\(\)/);
    });

    it("reports failures through describeCreateFailure (no raw 'failed' claim for a lost response)", () => {
      assert.match(source, /describeCreateFailure\(/);
      assert.doesNotMatch(source, /"Create (income|expense) failed"/);
    });

    it("applies no speculative local balance or cache edit on create", () => {
      assert.doesNotMatch(source, /setQueryData|setQueriesData/);
    });
  });
}

describe("the create services", () => {
  it("never retry or wrap a POST themselves: they go through apiRequest only", () => {
    for (const path of ["src/features/income/income.service.ts", "src/features/expenses/expense.service.ts"]) {
      const source = code(path);

      assert.doesNotMatch(source, /retry|setTimeout|fetch\(/i);
      assert.match(source, /method: "POST"/);
    }
  });
});
