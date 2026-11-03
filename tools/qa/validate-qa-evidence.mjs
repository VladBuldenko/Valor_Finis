#!/usr/bin/env node
// Validates the QA-0 documents and every committed run record.
// Usage: node tools/qa/validate-qa-evidence.mjs [repository-root]
// Exit code 0 = no finding, 1 = findings, 2 = usage or I/O error.
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { validateRepo } from "./qa-lib.mjs";

const root = resolve(process.argv[2] ?? resolve(dirname(fileURLToPath(import.meta.url)), "../.."));

try {
  const { errors, summary } = validateRepo(root);

  for (const line of summary) {
    console.log(line);
  }

  if (errors.length > 0) {
    console.error(`\n${errors.length} finding(s):`);

    for (const message of errors) {
      console.error(`  - ${message}`);
    }

    process.exit(1);
  }

  console.log("QA evidence validation: OK (structure and consistency only; it does not prove a test was run)");
} catch (error) {
  console.error(`QA evidence validation could not run: ${error instanceof Error ? error.message : String(error)}`);
  process.exit(2);
}
