// Runs the pure unit tests (src/**/*.test.ts and *.test.mjs) with Node's built-in
// test runner; no Metro, simulator, network or Supabase involved.
//
// `node --test` exits 0 when its glob matches nothing, which would let a
// renamed or moved test directory pass CI silently, so discovery is explicit
// and an empty result is a failure.
const { spawnSync } = require("node:child_process");
const { readdirSync } = require("node:fs");
const { join } = require("node:path");

function findTests(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);

    if (entry.isDirectory()) {
      return findTests(path);
    }

    return /\.test\.(ts|mjs)$/.test(entry.name) ? [path] : [];
  });
}

const files = findTests("src").sort();

if (files.length === 0) {
  console.error("No *.test.ts or *.test.mjs files found under src/: refusing to pass with zero tests.");
  process.exit(1);
}

const result = spawnSync(
  process.execPath,
  ["--experimental-strip-types", "--disable-warning=ExperimentalWarning", "--test", ...files],
  { stdio: "inherit" },
);

process.exit(result.status === null ? 1 : result.status);
