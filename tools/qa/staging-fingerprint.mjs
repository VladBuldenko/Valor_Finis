#!/usr/bin/env node
// Proves which environment a build targets WITHOUT printing any URL, path, credential or key.
// Reads EXPO_PUBLIC_API_URL and EXPO_PUBLIC_SUPABASE_URL (the same values used for the build)
// and compares their origin fingerprints with the owner-approved staging register.
//
// Usage: node tools/qa/staging-fingerprint.mjs --register <register.md> --staging <STG-id>
// Exit code 0 = both origins match the named ACTIVE staging entry and no denylist entry.
//           1 = mismatch, denylist hit, missing/invalid value, no ACTIVE staging entry
//               or no owner-approved production denylist entry.
import { readFileSync } from "node:fs";

import { approvedDenylist, originFingerprint, parseStagingRegister } from "./qa-lib.mjs";

function argument(name) {
  const index = process.argv.indexOf(name);

  return index === -1 ? undefined : process.argv[index + 1];
}

const registerPath = argument("--register");
const stagingId = argument("--staging");

if (!registerPath || !stagingId) {
  console.error("Usage: staging-fingerprint.mjs --register <register.md> --staging <STG-id>");
  process.exit(2);
}

const { staging, denylist } = parseStagingRegister(readFileSync(registerPath, "utf8"));
const entry = staging.find((candidate) => candidate["Staging ID"] === stagingId);
const denied = new Set(denylist.map((row) => row.Fingerprint));
const failures = [];

if (!entry || entry.Status !== "ACTIVE") {
  failures.push(`${stagingId} is not an ACTIVE staging entry in the register`);
}

// Without owner-recorded production fingerprints a staging match cannot rule production out.
if (approvedDenylist(denylist).length === 0) {
  failures.push("the register has no owner-approved production denylist entry");
}

// Which variable is checked against which register column.
const checks = [
  ["EXPO_PUBLIC_API_URL", "API origin fingerprint"],
  ["EXPO_PUBLIC_SUPABASE_URL", "Auth project fingerprint"],
];

for (const [variable, column] of checks) {
  const value = process.env[variable];

  if (!value) {
    failures.push(`${variable} is not set`);
    console.log(`${variable}: NOT SET`);
    continue;
  }

  const fingerprint = originFingerprint(value);

  if (fingerprint === null) {
    failures.push(`${variable} is not a valid http(s) URL`);
    console.log(`${variable}: INVALID`);
    continue;
  }

  if (!value.startsWith("https://")) {
    failures.push(`${variable} is not https (physical-device runs must use an https staging endpoint)`);
  }

  if (denied.has(fingerprint)) {
    failures.push(`${variable} matches the PRODUCTION denylist`);
  }

  const matches = entry?.[column] === fingerprint;

  if (!matches) {
    failures.push(`${variable} does not match ${stagingId} (${column})`);
  }

  console.log(`${variable}: ${fingerprint} ${matches ? "matches" : "DOES NOT MATCH"} ${stagingId}`);
}

console.log(`EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY: ${process.env.EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY ? "set" : "not set"} (value never printed)`);

if (failures.length > 0) {
  console.error("\nStaging isolation: NOT VERIFIED");

  for (const failure of failures) {
    console.error(`  - ${failure}`);
  }

  process.exit(1);
}

console.log(`\nStaging isolation: VERIFIED against ${stagingId}`);
