import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { COPY, MODE_COPY } from "./financial-rule-copy.ts";
import {
  extractStringLiterals,
  findForbiddenCopy,
  stripComments,
} from "./financial-rule-forbidden-copy.ts";
import { KNOWN_REASON_CODES, reasonText } from "./financial-rule-presentation.ts";

const HERE = dirname(fileURLToPath(import.meta.url));

describe("the forbidden-copy rules themselves", () => {
  const forbidden = [
    "Your total balance is 5",
    "Combined balance",
    "Safe to spend today",
    "Available cash",
    "Rules run while you sleep",
    "Works even when the app is closed",
    "Runs in the background",
    "Unattended execution",
    "Checked 24/7",
    "We transfer the money to your Goal",
    "Funds deposited into the reservation",
    "Your Goal receives a payment",
    "3 unread alerts",
    "This is guaranteed",
  ];
  const allowed = [
    "Rules are checked when you open or refresh the app and after you record income.",
    "A reservation sets money aside inside an Account for a Goal. It does not move any money in your bank.",
    "Available to reserve",
    "Needs your attention",
  ];

  it("flags every forbidden phrase", () => {
    for (const text of forbidden) {
      assert.ok(findForbiddenCopy(text).length > 0, text);
    }
  });

  it("does not flag the approved wording", () => {
    for (const text of allowed) {
      assert.deepEqual(findForbiddenCopy(text), [], text);
    }
  });

  it("strips comments but keeps '//' inside strings", () => {
    const source = 'const a = "http://x"; // safe to spend\n/* total balance */ const b = "ok";';

    assert.deepEqual(extractStringLiterals(source), ["http://x", "ok"]);
    assert.ok(!stripComments(source).includes("safe to spend"));
  });
});

describe("the Smart Rules feature contains no forbidden copy", () => {
  const files = readdirSync(HERE).filter(
    (name) => /\.(ts|tsx)$/.test(name) && !/\.test\.ts$/.test(name) && name !== "financial-rule-forbidden-copy.ts",
  );

  it("scans the feature's source files", () => {
    assert.ok(files.length >= 8, "the scan must see the feature files");
  });

  for (const name of files) {
    it(name, () => {
      const hits = extractStringLiterals(readFileSync(join(HERE, name), "utf8")).flatMap(findForbiddenCopy);

      assert.deepEqual(hits, []);
    });
  }

  it("every reason text and the copy constants are clean", () => {
    const texts = [
      ...Object.values(COPY),
      ...Object.values(MODE_COPY).map((mode) => mode.description),
      ...KNOWN_REASON_CODES.map((code) => String(reasonText(code))),
    ];

    for (const text of texts) {
      assert.deepEqual(findForbiddenCopy(text), [], text);
    }
  });

  it("AUTO copy states when rules are checked and promises nothing unattended (C1)", () => {
    assert.match(MODE_COPY.AUTO.description, /open or refresh the app and after you record income/);
  });

  it("uses 'available to reserve' wording (C3)", () => {
    assert.equal(COPY.reservableLabel, "Available to reserve");
  });
});
