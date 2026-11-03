// Tests of the QA-0 validator. Run: node --test tools/qa/
// Fixtures that look like secrets are assembled from fragments so this file does not trip the scan it tests.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { after, describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import {
  checkAcceptance,
  checkProcedures,
  checkStagingRegister,
  findStaleFloors,
  originFingerprint,
  parseIsolationMatch,
  parseRowBlocks,
  scanForSecrets,
  validateRepo,
} from "./qa-lib.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const TEMPLATE = readFileSync(join(repoRoot, "docs/mvp/qa-device-acceptance-template.md"), "utf8");
const PROCEDURES = readFileSync(join(repoRoot, "docs/mvp/qa-security-regression-procedures.md"), "utf8");

const SHA = "0123456789abcdef0123456789abcdef01234567";
const TODAY = "2026-12-01";
const temps = [];

after(() => {
  for (const dir of temps) {
    rmSync(dir, { recursive: true, force: true });
  }
});

const baseCtx = (extra = {}) => ({
  today: TODAY,
  fileExists: (path) => path === "docs/mvp/qa-evidence/QA4-20261120-01/artifacts/ok.png",
  staging: [{ "Staging ID": "STG-1", Status: "ACTIVE" }],
  waivers: [],
  ...extra,
});

// Replaces one field value inside one row block of an acceptance document.
function setField(text, rowId, field, value) {
  const start = text.indexOf(`#### ${rowId} `);
  assert.notEqual(start, -1, `row ${rowId} not found`);
  const end = text.indexOf("\n#### ", start + 1);
  const block = text.slice(start, end === -1 ? undefined : end);
  const pattern = new RegExp(`^\\| ${field} \\|.*$`, "m");
  assert.match(block, pattern, `field ${field} not found in ${rowId}`);

  return text.slice(0, start) + block.replace(pattern, `| ${field} | ${value} |`) + (end === -1 ? "" : text.slice(end));
}

function passRow(text, rowId, overrides = {}) {
  const values = {
    "Device model and OS": "Device X, OS 99",
    "App build identifier": `${SHA} (local-lan)`,
    "Staging environment identifier": "STG-1",
    "Actual result": "Observed as expected",
    "Evidence location": "docs/mvp/qa-evidence/QA4-20261120-01/artifacts/ok.png",
    "Defect reference": "none",
    Tester: "tester-1",
    "Execution date": "2026-11-20",
    Status: "PASS",
    ...overrides,
  };

  return Object.entries(values).reduce((acc, [field, value]) => setField(acc, rowId, field, value), text);
}

describe("the committed template", () => {
  it("has exactly 40 rows: J01–J20 once on each platform", () => {
    const blocks = parseRowBlocks(TEMPLATE);

    assert.equal(blocks.length, 40);

    for (const key of ["IOS", "AND"]) {
      for (let n = 1; n <= 20; n += 1) {
        const id = `ACC-${key}-J${String(n).padStart(2, "0")}`;

        assert.equal(blocks.filter((block) => block.heading === id).length, 1, id);
      }
    }
  });

  it("validates with no findings and contains no executed result", () => {
    assert.deepEqual(checkAcceptance(TEMPLATE, baseCtx(), "template"), []);

    const statuses = parseRowBlocks(TEMPLATE).map((block) => block.fields.get("Status"));

    assert.equal(statuses.filter((status) => status === "NOT RUN").length, 36);
    assert.equal(statuses.filter((status) => status === "BLOCKED").length, 4);
    assert.equal(statuses.filter((status) => status === "PASS" || status === "WAIVED").length, 0);
  });

  it("keeps J19 and J20 blocked on both platforms and J18 buildable", () => {
    const status = (id) => parseRowBlocks(TEMPLATE).find((block) => block.heading === id).fields.get("Status");

    for (const key of ["IOS", "AND"]) {
      assert.equal(status(`ACC-${key}-J19`), "BLOCKED");
      assert.equal(status(`ACC-${key}-J20`), "BLOCKED");
      assert.equal(status(`ACC-${key}-J18`), "NOT RUN");
    }
  });
});

describe("structure checks", () => {
  it("reports a missing journey", () => {
    const start = TEMPLATE.indexOf("#### ACC-AND-J20 ");
    const broken = TEMPLATE.slice(0, start);
    const errors = checkAcceptance(broken, baseCtx(), "template");

    assert.ok(errors.some((message) => message.includes("Android: missing journeys J20")));
    assert.ok(errors.some((message) => message.includes("expected exactly 40")));
  });

  it("reports a duplicate journey/platform row", () => {
    const start = TEMPLATE.indexOf("#### ACC-IOS-J01 ");
    const end = TEMPLATE.indexOf("\n#### ", start + 1);
    const duplicated = TEMPLATE + "\n" + TEMPLATE.slice(start, end);
    const errors = checkAcceptance(duplicated, baseCtx(), "template");

    assert.ok(errors.some((message) => message.includes("duplicate journey/platform row")));
  });

  it("reports a missing or renamed mandatory field", () => {
    const missing = TEMPLATE.replace(/^\| Financial invariants \|.*\n/m, "");

    assert.ok(checkAcceptance(missing, baseCtx(), "template").some((message) => message.includes('missing mandatory field "Financial invariants"')));

    const renamed = TEMPLATE.replace("| Evidence location |", "| Evidence |");
    const errors = checkAcceptance(renamed, baseCtx(), "template");

    assert.ok(errors.some((message) => message.includes('unknown field "Evidence"')));
    assert.ok(errors.some((message) => message.includes('missing mandatory field "Evidence location"')));
  });

  it("reports an emptied specification field", () => {
    const emptied = setField(TEMPLATE, "ACC-IOS-J05", "Test actions", "—");

    assert.ok(checkAcceptance(emptied, baseCtx(), "template").some((message) => message.includes('"Test actions" is empty')));
  });

  it("reports a journey outside J01–J20", () => {
    const extra = TEMPLATE.replace("#### ACC-IOS-J01 ", "#### ACC-IOS-J21 ").replace("| Row ID | ACC-IOS-J01 |", "| Row ID | ACC-IOS-J21 |");

    assert.ok(checkAcceptance(extra, baseCtx(), "template").some((message) => message.includes("outside J01–J20")));
  });

  it("does not allow the blank template to carry a PASS", () => {
    const text = passRow(TEMPLATE, "ACC-IOS-J01");

    assert.ok(checkAcceptance(text, baseCtx(), "template").some((message) => message.includes("blank template may contain only")));
  });

  it("requires NOT RUN rows to leave result fields empty", () => {
    const text = setField(TEMPLATE, "ACC-IOS-J02", "Actual result", "looked fine");

    assert.ok(checkAcceptance(text, baseCtx(), "template").some((message) => message.includes('NOT RUN row must leave "Actual result"')));
  });

  it("requires a reason and a blocker on BLOCKED", () => {
    const text = setField(setField(TEMPLATE, "ACC-IOS-J19", "Actual result", "—"), "ACC-IOS-J19", "Blocker reference", "—");
    const errors = checkAcceptance(text, baseCtx(), "template");

    assert.ok(errors.some((message) => message.includes("BLOCKED needs an Actual result")));
    assert.ok(errors.some((message) => message.includes("BLOCKED needs a Blocker reference")));
  });
});

describe("PASS needs evidence", () => {
  const run = (text) => checkAcceptance(text, baseCtx(), "run");

  it("accepts a fully evidenced PASS", () => {
    assert.deepEqual(run(passRow(TEMPLATE, "ACC-IOS-J01")), []);
  });

  it("rejects a PASS with no evidence, a missing file or a path outside the evidence tree", () => {
    assert.ok(run(passRow(TEMPLATE, "ACC-IOS-J01", { "Evidence location": "—" })).some((message) => message.includes("needs an Evidence location")));
    assert.ok(run(passRow(TEMPLATE, "ACC-IOS-J01", { "Evidence location": "docs/mvp/qa-evidence/QA4-20261120-01/artifacts/missing.png" })).some((message) => message.includes("does not exist")));
    assert.ok(run(passRow(TEMPLATE, "ACC-IOS-J01", { "Evidence location": "../secrets.txt" })).some((message) => message.includes("must be a file path under")));
  });

  it("rejects a PASS without device, a full SHA, a tester, a real past date or an ACTIVE staging id", () => {
    assert.ok(run(passRow(TEMPLATE, "ACC-IOS-J01", { "Device model and OS": "TBD (owner)" })).some((message) => message.includes('needs "Device model and OS"')));
    assert.ok(run(passRow(TEMPLATE, "ACC-IOS-J01", { "App build identifier": "abc1234" })).some((message) => message.includes("40-character commit SHA")));
    assert.ok(run(passRow(TEMPLATE, "ACC-IOS-J01", { Tester: "—" })).some((message) => message.includes("needs a Tester")));
    assert.ok(run(passRow(TEMPLATE, "ACC-IOS-J01", { "Execution date": "2027-01-01" })).some((message) => message.includes("not in the future")));
    assert.ok(run(passRow(TEMPLATE, "ACC-IOS-J01", { "Execution date": "2026-02-30" })).some((message) => message.includes("Execution date")));
    assert.ok(run(passRow(TEMPLATE, "ACC-IOS-J01", { "Staging environment identifier": "STG-9" })).some((message) => message.includes("not in the staging register")));
  });

  it("rejects a PASS against a staging entry that is not ACTIVE", () => {
    const ctx = baseCtx({ staging: [{ "Staging ID": "STG-1", Status: "NOT PROVISIONED" }] });

    assert.ok(checkAcceptance(passRow(TEMPLATE, "ACC-IOS-J01"), ctx, "run").some((message) => message.includes("is not ACTIVE")));
  });

  it("rejects a PASS when staging isolation was not verified or the build differs from the run record", () => {
    assert.ok(checkAcceptance(passRow(TEMPLATE, "ACC-IOS-J01"), baseCtx({ isolationVerified: false }), "run").some((message) => message.includes("Staging isolation: VERIFIED")));
    assert.ok(checkAcceptance(passRow(TEMPLATE, "ACC-IOS-J01"), baseCtx({ appSha: "f".repeat(40) }), "run").some((message) => message.includes("does not match the run record")));
  });

  it("rejects a PASS that references an open Sev-1 or Sev-2 defect, accepts Sev-3", () => {
    const defects = new Map([
      ["DEF-001", { "Defect ID": "DEF-001", Severity: "Sev-2", Status: "open" }],
      ["DEF-002", { "Defect ID": "DEF-002", Severity: "Sev-3", Status: "open" }],
    ]);

    assert.ok(checkAcceptance(passRow(TEMPLATE, "ACC-IOS-J01", { "Defect reference": "DEF-001" }), baseCtx({ defects }), "run").some((message) => message.includes("open Sev-2")));
    assert.deepEqual(checkAcceptance(passRow(TEMPLATE, "ACC-IOS-J01", { "Defect reference": "DEF-002" }), baseCtx({ defects }), "run"), []);
  });

  it("requires a defect reference on FAIL", () => {
    assert.ok(run(passRow(TEMPLATE, "ACC-IOS-J01", { Status: "FAIL" })).some((message) => message.includes("FAIL needs a Defect reference")));
  });
});

describe("waivers", () => {
  const signed = {
    "Waiver ID": "WAIVER-J18-1",
    Journey: "J18",
    Authority: "BR-5; GAP-20",
    Platforms: "iOS; Android",
    "Waived element": "History screen",
    Reason: "Owner decision",
    Owner: "Owner",
    "Signed on": "2026-11-25",
    "Decision record reference": "decision-record",
    Status: "SIGNED",
  };
  const waive = (id, ref, overrides = {}) =>
    passRow(TEMPLATE, id, { Status: "WAIVED", "Evidence location": "—", Tester: "—", "Execution date": "—", "Actual result": "Waived under BR-5", ...overrides, "Waiver reference": ref });

  it("never waives a journey other than J18", () => {
    const ctx = baseCtx({ waivers: [{ ...signed, "Waiver ID": "WAIVER-J18-1" }] });

    assert.ok(checkAcceptance(waive("ACC-IOS-J05", "WAIVER-J18-1"), ctx, "run").some((message) => message.includes("only J18 may be WAIVED")));
  });

  it("rejects a J18 waiver with no register entry", () => {
    assert.ok(checkAcceptance(waive("ACC-IOS-J18", "WAIVER-J18-1"), baseCtx(), "run").some((message) => message.includes("not in the waiver register")));
  });

  it("rejects an unsigned or incomplete register entry", () => {
    const unsigned = baseCtx({ waivers: [{ ...signed, Status: "DRAFT" }] });
    const incomplete = baseCtx({ waivers: [{ ...signed, Owner: "—" }] });

    assert.ok(checkAcceptance(waive("ACC-IOS-J18", "WAIVER-J18-1"), unsigned, "run").some((message) => message.includes("is not SIGNED")));
    assert.ok(checkAcceptance(waive("ACC-IOS-J18", "WAIVER-J18-1"), incomplete, "run").some((message) => message.includes('has no "Owner"')));
  });

  it("accepts a J18 waiver backed by a complete signed entry", () => {
    assert.deepEqual(checkAcceptance(waive("ACC-IOS-J18", "WAIVER-J18-1"), baseCtx({ waivers: [signed] }), "run"), []);
  });

  it("rejects a waiver reference on a row that is not WAIVED, and a malformed reference", () => {
    const stray = setField(TEMPLATE, "ACC-IOS-J18", "Waiver reference", "WAIVER-J18-1");

    assert.ok(checkAcceptance(stray, baseCtx({ waivers: [signed] }), "template").some((message) => message.includes("only allowed on a WAIVED row")));
    assert.ok(checkAcceptance(waive("ACC-IOS-J18", "AUTO"), baseCtx({ waivers: [signed] }), "run").some((message) => message.includes("WAIVER-J18-<n>")));
  });

  it("rejects an iOS-only waiver on the Android row and an Android-only waiver on the iOS row", () => {
    const iosOnly = baseCtx({ waivers: [{ ...signed, Platforms: "iOS" }] });
    const androidOnly = baseCtx({ waivers: [{ ...signed, Platforms: "Android" }] });

    assert.deepEqual(checkAcceptance(waive("ACC-IOS-J18", "WAIVER-J18-1"), iosOnly, "run"), []);
    assert.deepEqual(checkAcceptance(waive("ACC-AND-J18", "WAIVER-J18-1"), androidOnly, "run"), []);
    assert.ok(checkAcceptance(waive("ACC-AND-J18", "WAIVER-J18-1"), iosOnly, "run").some((message) => message.includes("covers iOS but this row is Android")));
    assert.ok(checkAcceptance(waive("ACC-IOS-J18", "WAIVER-J18-1"), androidOnly, "run").some((message) => message.includes("covers Android but this row is iOS")));
  });

  it("accepts a two-platform waiver on both rows", () => {
    const both = baseCtx({ waivers: [{ ...signed, Platforms: "iOS and Android" }] });

    assert.deepEqual(checkAcceptance(waive("ACC-IOS-J18", "WAIVER-J18-1"), both, "run"), []);
    assert.deepEqual(checkAcceptance(waive("ACC-AND-J18", "WAIVER-J18-1"), both, "run"), []);
  });

  it("rejects a waiver whose Platforms cell is empty, unknown or free text", () => {
    for (const Platforms of ["—", "everything", "iOS; Windows", "all"]) {
      const ctx = baseCtx({ waivers: [{ ...signed, Platforms }] });
      const errors = checkAcceptance(waive("ACC-IOS-J18", "WAIVER-J18-1"), ctx, "run");

      assert.ok(errors.some((message) => message.includes("must list its platforms") || message.includes('has no "Platforms"')), `${Platforms}: ${errors}`);
    }
  });

  it("flags a signed register entry for any journey other than J18", () => {
    const root = makeRepo({ waivers: `| ${Object.keys(signed).join(" | ")} |\n|${Object.keys(signed).map(() => "---").join("|")}|\n| ${Object.values({ ...signed, Journey: "J05" }).join(" | ")} |` });
    const { errors } = validateRepo(root, { today: TODAY });

    assert.ok(errors.some((message) => message.includes("only J18 may be waived")));
  });
});

describe("procedure results", () => {
  it("has 36 rows: SP-01–SP-18 on both platforms, all blank", () => {
    assert.deepEqual(checkProcedures(PROCEDURES, baseCtx(), "template"), []);
  });

  it("rejects a procedure PASS without evidence and any WAIVED procedure", () => {
    const first = PROCEDURES.split("\n").find((line) => line.startsWith("| SPR-IOS-01 "));
    const cells = first.split("|");
    const passed = [...cells];
    passed[4] = " PASS ";
    const waived = [...cells];
    waived[4] = " WAIVED ";

    assert.ok(checkProcedures(PROCEDURES.replace(first, passed.join("|")), baseCtx(), "run").some((message) => message.includes("PASS needs")));
    assert.ok(checkProcedures(PROCEDURES.replace(first, waived.join("|")), baseCtx(), "run").some((message) => message.includes("cannot be WAIVED")));
  });

  it("reports a missing procedure row", () => {
    const line = PROCEDURES.split("\n").find((entry) => entry.startsWith("| SPR-AND-18 "));
    const errors = checkProcedures(PROCEDURES.replace(`${line}\n`, ""), baseCtx(), "template");

    assert.ok(errors.some((message) => message.includes("missing procedure result SP-18 on Android")));
  });
});

describe("stale operating-system floors", () => {
  it("flags iOS versions below 16.4 and Android API levels below 24", () => {
    const text = ["Floors are iOS 15.1 and Android API 24.", "We support iOS 14.", "minSdk = 21", "Android API 23 only"].join("\n");
    const found = findStaleFloors(text).map((hit) => hit.what);

    assert.deepEqual(found, ["iOS 15.1", "iOS 14", "Android API 21", "Android API 23"]);
  });

  it("accepts the pinned floors, newer systems and recorded exceptions", () => {
    const text = [
      "Floors are iOS 16.4 and Android API 24.",
      "Current simulator iOS 26.3.",
      "The value iOS 15.1 was superseded (QA-0 superseded: see matrix).",
      "Quoted for history (QA-0 exception) iOS 15.1.",
    ].join("\n");

    assert.deepEqual(findStaleFloors(text), []);
  });

  it("is enforced across the repository documents", () => {
    const root = makeRepo({ extraDoc: ["docs/mvp/other.md", "Supported from iOS 15.1 upward.\n"] });

    assert.ok(validateRepo(root, { today: TODAY }).errors.some((message) => message.includes('stale OS floor "iOS 15.1"')));
  });
});

describe("production endpoints and credentials", () => {
  const jwt = ["eyJ", "hbGciOiJIUzI1NiJ9", ".", "abcdefghijklmnop", ".", "qrstuvwxyz012345"].join("");
  const key = ["sb_", "publishable_", "AbCdEfGh12345678"].join("");
  const host = ["abcdefghij", "supabase", "co"].join(".");
  const render = ["valor-api", "onrender", "com"].join(".");
  const dbUrl = ["post", "gres://", "app:", "hunter2", "@db.internal"].join("");
  const lan = ["192", "168", "1", "20"].join(".");

  it("finds each token, key, hostname, connection string and LAN address", () => {
    const text = [jwt, key, `https://${host}/auth/v1`, `https://${render}`, dbUrl, `http://${lan}:8081`, `Bearer ${"a".repeat(30)}`, "service_role=" + "x".repeat(30)].join("\n");
    const found = scanForSecrets(text).join(" | ");

    for (const expected of ["JSON Web Token", "Supabase key", "hosted back-end hostname", "database URL with credentials", "private network address", "bearer token", "service role value", "non-allowlisted host"]) {
      assert.ok(found.includes(expected), `${expected} not found in: ${found}`);
    }
  });

  it("does not flag the documentation wording or allowlisted links", () => {
    const text = "Never commit a service_role value or a key such as sb_publishable_… Use https://docs.expo.dev/versions/v57.0.0/ and qa-a@example.test.";

    assert.deepEqual(scanForSecrets(text), []);
  });

  it("flags a real email address", () => {
    assert.ok(scanForSecrets(["contact someone", "@", "gmail", ".com"].join("")).some((finding) => finding.includes("non-example domain")));
  });

  it("fails the repository check for a secret inside a run directory", () => {
    const root = makeRepo({ runFile: ["docs/mvp/qa-evidence/QA4-20261120-01/artifacts/log.txt", `token ${jwt}\n`] });

    assert.ok(validateRepo(root, { today: TODAY }).errors.some((message) => message.includes("JSON Web Token")));
  });
});

describe("staging register and fingerprint", () => {
  const fp = (n) => `fp1:${String(n).repeat(16).slice(0, 16)}`;
  const register = (staging, deny) => `## Staging environments

| Staging ID | Status | API origin fingerprint | Auth project fingerprint | Database host fingerprint | Approved by | Approved on |
|---|---|---|---|---|---|---|
${staging}

## Production denylist

| Fingerprint | What it identifies | Recorded by | Recorded on |
|---|---|---|---|
${deny}
`;

  it("normalizes the origin and drops path, query, credentials and default ports", () => {
    const base = originFingerprint("https://Example.TEST/");

    assert.match(base, /^fp1:[0-9a-f]{16}$/);
    assert.equal(originFingerprint("https://example.test:443/rest/v1/?apikey=abc"), base);
    assert.equal(originFingerprint(["https://", "user", ":pw@", "example.test/path"].join("")), base);
    assert.notEqual(originFingerprint("https://example.test:8443"), base);
    assert.notEqual(originFingerprint("https://other.example.test"), base);
    assert.equal(originFingerprint("not a url"), null);
    assert.equal(originFingerprint("ftp://example.test"), null);
  });

  it("requires owner approval and valid fingerprints on an ACTIVE entry", () => {
    const text = register(`| STG-1 | ACTIVE | ${fp(1)} | bad | ${fp(3)} | — | — |`, "| (none) | — | — | — |");
    const errors = checkStagingRegister(text);

    assert.ok(errors.some((message) => message.includes('"Auth project fingerprint" must be')));
    assert.ok(errors.some((message) => message.includes('"Approved by"')));
  });

  it("rejects a fingerprint that is both staging and on the production denylist", () => {
    const text = register(`| STG-1 | ACTIVE | ${fp(1)} | ${fp(2)} | ${fp(3)} | Owner | 2026-11-20 |`, `| ${fp(2)} | production auth | Owner | 2026-11-20 |`);

    assert.ok(checkStagingRegister(text).some((message) => message.includes("both ACTIVE staging and on the production denylist")));
  });

  it("refuses an ACTIVE staging entry when the production denylist is empty or not owner-approved", () => {
    const active = `| STG-1 | ACTIVE | ${fp(1)} | ${fp(2)} | ${fp(3)} | Owner | 2026-11-20 |`;
    const required = "requires at least one owner-approved production denylist entry";

    assert.ok(checkStagingRegister(register(active, "| (none) | — | — | — |")).some((message) => message.includes(required)));
    assert.ok(checkStagingRegister(register(active, `| ${fp(9)} | production API | — | — |`)).some((message) => message.includes(required)));
    assert.ok(checkStagingRegister(register(active, `| ${fp(9)} | production API | Owner | not-a-date |`)).some((message) => message.includes(required)));
    assert.ok(checkStagingRegister(register(active, `| ${fp(9)} | production API | — | — |`)).some((message) => message.includes('needs "Recorded by"')));
  });

  it("accepts an ACTIVE staging entry with an owner-approved denylist entry", () => {
    const active = `| STG-1 | ACTIVE | ${fp(1)} | ${fp(2)} | ${fp(3)} | Owner | 2026-11-20 |`;

    assert.deepEqual(checkStagingRegister(register(active, `| ${fp(9)} | production API | Owner | 2026-11-19 |`)), []);
  });

  it("keeps the initial NOT PROVISIONED register with an empty denylist valid", () => {
    const initial = register("| (none) | NOT PROVISIONED | — | — | — | — | — |", "| (none) | — | — | — |");

    assert.deepEqual(checkStagingRegister(initial), []);
  });

  it("accepts the committed, empty register", () => {
    assert.deepEqual(checkStagingRegister(readFileSync(join(repoRoot, "docs/mvp/qa-evidence/staging-register.md"), "utf8")), []);
  });

  describe("the command line helper", () => {
    const dir = mkdtempSync(join(tmpdir(), "qa-fp-"));
    temps.push(dir);
    const apiFp = originFingerprint("https://api.example.test");
    const authFp = originFingerprint("https://auth.example.test");
    const prodFp = originFingerprint("https://prod.example.test");
    const registerFile = join(dir, "register.md");
    writeFileSync(registerFile, register(`| STG-1 | ACTIVE | ${apiFp} | ${authFp} | ${fp(3)} | Owner | 2026-11-20 |`, `| ${prodFp} | production API | Owner | 2026-11-20 |`));
    const cli = join(here, "staging-fingerprint.mjs");
    const run = (env) =>
      spawnSync(process.execPath, [cli, "--register", registerFile, "--staging", "STG-1"], {
        env: { PATH: process.env.PATH, ...env },
        encoding: "utf8",
      });

    it("verifies a staging build and never prints the URL or the key", () => {
      const result = run({
        EXPO_PUBLIC_API_URL: "https://api.example.test/v1",
        EXPO_PUBLIC_SUPABASE_URL: "https://auth.example.test",
        EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY: "secret-key-value-1234",
      });

      assert.equal(result.status, 0, result.stderr);
      assert.match(result.stdout, /Staging isolation: VERIFIED against STG-1/);
      assert.doesNotMatch(result.stdout + result.stderr, /example\.test|secret-key-value|\/v1/);
    });

    it("never reports VERIFIED when the register has no owner-approved production denylist entry", () => {
      const env = { EXPO_PUBLIC_API_URL: "https://api.example.test", EXPO_PUBLIC_SUPABASE_URL: "https://auth.example.test" };

      for (const denylist of ["| (none) | — | — | — |", `| ${prodFp} | production API | — | — |`]) {
        const file = join(dir, "register-no-denylist.md");
        writeFileSync(file, register(`| STG-1 | ACTIVE | ${apiFp} | ${authFp} | ${fp(3)} | Owner | 2026-11-20 |`, denylist));
        const result = spawnSync(process.execPath, [cli, "--register", file, "--staging", "STG-1"], { env: { PATH: process.env.PATH, ...env }, encoding: "utf8" });

        assert.equal(result.status, 1);
        assert.match(result.stderr, /no owner-approved production denylist entry/);
        assert.match(result.stderr, /NOT VERIFIED/);
        assert.doesNotMatch(result.stdout, /Staging isolation: VERIFIED/);
      }
    });

    it("refuses a plain http URL even when its fingerprint is the registered one", () => {
      const plain = join(dir, "register-http.md");
      writeFileSync(plain, register(`| STG-1 | ACTIVE | ${originFingerprint("http://api.example.test")} | ${authFp} | ${fp(3)} | Owner | 2026-11-20 |`, `| ${prodFp} | production API | Owner | 2026-11-20 |`));
      const result = spawnSync(process.execPath, [cli, "--register", plain, "--staging", "STG-1"], {
        env: { PATH: process.env.PATH, EXPO_PUBLIC_API_URL: "http://api.example.test", EXPO_PUBLIC_SUPABASE_URL: "https://auth.example.test" },
        encoding: "utf8",
      });

      assert.equal(result.status, 1);
      assert.match(result.stderr, /not https/);
    });

    it("refuses a production fingerprint, a mismatch, a missing variable and a plain http URL", () => {
      const production = run({ EXPO_PUBLIC_API_URL: "https://prod.example.test", EXPO_PUBLIC_SUPABASE_URL: "https://auth.example.test" });

      assert.equal(production.status, 1);
      assert.match(production.stderr, /PRODUCTION denylist/);
      assert.equal(run({ EXPO_PUBLIC_API_URL: "https://elsewhere.example.test", EXPO_PUBLIC_SUPABASE_URL: "https://auth.example.test" }).status, 1);
      assert.equal(run({ EXPO_PUBLIC_API_URL: "https://api.example.test" }).status, 1);
      assert.equal(run({ EXPO_PUBLIC_API_URL: "http://api.example.test", EXPO_PUBLIC_SUPABASE_URL: "https://auth.example.test" }).status, 1);
    });
  });
});

// A repository fixture: the real QA documents copied into a temporary root.
function makeRepo({ waivers, extraDoc, runFile } = {}) {
  const root = mkdtempSync(join(tmpdir(), "qa-repo-"));
  temps.push(root);
  mkdirSync(join(root, "docs/mvp"), { recursive: true });
  cpSync(join(repoRoot, "docs/mvp/qa-evidence"), join(root, "docs/mvp/qa-evidence"), { recursive: true });

  for (const name of ["qa-device-acceptance-template.md", "qa-security-regression-procedures.md"]) {
    cpSync(join(repoRoot, "docs/mvp", name), join(root, "docs/mvp", name));
  }

  if (waivers) {
    const original = readFileSync(join(root, "docs/mvp/qa-evidence/waivers.md"), "utf8");
    writeFileSync(join(root, "docs/mvp/qa-evidence/waivers.md"), original.replace(/\| Waiver ID[\s\S]*$/, `${waivers}\n`));
  }

  for (const [path, content] of [extraDoc, runFile].filter(Boolean)) {
    mkdirSync(dirname(join(root, path)), { recursive: true });
    writeFileSync(join(root, path), content);
  }

  return root;
}

describe("a complete run directory", () => {
  const RUN = "QA4-20261120-01";
  const fpOf = (n) => `fp1:${String(n).repeat(16).slice(0, 16)}`;

  function makeRun({
    isolation = "Staging isolation: VERIFIED. Fingerprint check artifacts/staging-fingerprint.txt matched STG-1; corroboration seed marker.",
    mutate = (text) => text,
    mutateProcedures = (text) => text,
    denylist = `| ${fpOf(9)} | production API | Owner | 2026-11-19 |`,
    secondStaging = false,
    tenthStaging = false,
    runStaging = "STG-1",
    stg1Status = "ACTIVE",
  } = {}) {
    const root = makeRepo();
    const evidence = join(root, "docs/mvp/qa-evidence");
    const dir = join(evidence, RUN);
    mkdirSync(join(dir, "artifacts"), { recursive: true });
    writeFileSync(join(dir, "artifacts/ok.png"), "x");

    const rows = [`| STG-1 | ${stg1Status} | ${fpOf(1)} | ${fpOf(2)} | ${fpOf(3)} | Owner | 2026-11-19 |`];

    if (secondStaging) {
      rows.push(`| STG-2 | ACTIVE | ${fpOf(4)} | ${fpOf(5)} | ${fpOf(6)} | Owner | 2026-11-19 |`);
    }

    if (tenthStaging) {
      rows.push(`| STG-10 | ACTIVE | ${fpOf(7)} | ${fpOf(8)} | ${fpOf(1)} | Owner | 2026-11-19 |`);
    }

    const register = readFileSync(join(evidence, "staging-register.md"), "utf8")
      .replace("| (none) | NOT PROVISIONED | — | — | — | — | — |", rows.join("\n"))
      .replace("| (none) | — | — | — |", denylist);
    writeFileSync(join(evidence, "staging-register.md"), register);

    const fields = {
      "Run ID": RUN,
      "Gate and scope": "BR-5, J01 on iOS",
      "App commit SHA": SHA,
      "Backend commit SHA": SHA,
      "Backend migration head": "head of the backend commit",
      "App version": "1.0.0",
      "Build type": "expo-go",
      "Build channel": "local-lan",
      "Installation method": "Expo Go from the store, QR scan",
      "Staging environment identifier": runStaging,
      "Staging isolation line": isolation,
      Devices: "Device X, OS 99, reference, physical",
      "Network profile": "NW-W",
      "Accessibility settings": "AX-0",
      "Test users": "QA-A",
      Tester: "tester-1",
      "Started and finished": "2026-11-20T09:00Z / 2026-11-20T10:00Z",
      "Owner sign-off": "signoff.md",
    };
    writeFileSync(join(dir, "run-record.md"), `| Field | Content |\n|---|---|\n${Object.entries(fields).map(([k, v]) => `| ${k} | ${v} |`).join("\n")}\n`);
    writeFileSync(join(dir, "defects.md"), "## Defects\n\n| Defect ID | Severity | Status | Row IDs | Summary | Evidence | Owner |\n|---|---|---|---|---|---|---|\n| (none) | — | — | — | — | — | — |\n");
    writeFileSync(join(dir, "procedures.md"), mutateProcedures(readFileSync(join(root, "docs/mvp/qa-security-regression-procedures.md"), "utf8")));
    writeFileSync(join(dir, "acceptance.md"), mutate(readFileSync(join(root, "docs/mvp/qa-device-acceptance-template.md"), "utf8")));

    return root;
  }

  const passJ01 = (text) => passRow(text, "ACC-IOS-J01", { "Evidence location": `docs/mvp/qa-evidence/${RUN}/artifacts/ok.png` });

  it("accepts a verified run with one evidenced PASS and the rest NOT RUN", () => {
    assert.deepEqual(validateRepo(makeRun({ mutate: passJ01 }), { today: TODAY }).errors, []);
  });

  it("rejects a PASS when the run record says staging isolation was NOT VERIFIED", () => {
    const root = makeRun({ mutate: passJ01, isolation: "Staging isolation: NOT VERIFIED. Register not yet approved." });

    assert.ok(validateRepo(root, { today: TODAY }).errors.some((message) => message.includes("Staging isolation: VERIFIED")));
  });

  it("rejects a run record without an isolation statement", () => {
    const root = makeRun({ mutate: passJ01, isolation: "looks fine" });

    assert.ok(validateRepo(root, { today: TODAY }).errors.some((message) => message.includes('"Staging isolation line" must start with')));
  });

  it("refuses VERIFIED and every PASS when the register has no owner-approved production denylist entry", () => {
    const root = makeRun({ mutate: passJ01, denylist: "| (none) | — | — | — |" });
    const errors = validateRepo(root, { today: TODAY }).errors;

    assert.ok(errors.some((message) => message.includes("requires at least one owner-approved production denylist entry")));
    assert.ok(errors.some((message) => message.includes('"Staging isolation: VERIFIED" is not allowed while the register has no owner-approved')));
    assert.ok(errors.some((message) => message.includes("PASS is not allowed: the staging register has no owner-approved production denylist entry")));
  });

  describe("staging identity binding with two ACTIVE staging environments", () => {
    const withStaging = (stagingId) => (text) => passRow(passJ01(text), "ACC-IOS-J01", { "Staging environment identifier": stagingId });

    it("accepts a result for the run's own staging environment", () => {
      assert.deepEqual(validateRepo(makeRun({ secondStaging: true, mutate: withStaging("STG-1") }), { today: TODAY }).errors, []);
    });

    it("rejects a PASS row that names a different ACTIVE staging environment", () => {
      const errors = validateRepo(makeRun({ secondStaging: true, mutate: withStaging("STG-2") }), { today: TODAY }).errors;

      assert.ok(errors.some((message) => message.includes('staging identifier "STG-2" differs from the run record\'s "STG-1"')));
    });

    it("rejects a FAIL row that names a different ACTIVE staging environment", () => {
      const mutate = (text) => passRow(passJ01(text), "ACC-IOS-J01", { Status: "FAIL", "Staging environment identifier": "STG-2", "Defect reference": "DEF-001" });
      const root = makeRun({ secondStaging: true, mutate });
      writeFileSync(
        join(root, `docs/mvp/qa-evidence/${RUN}/defects.md`),
        "## Defects\n\n| Defect ID | Severity | Status | Row IDs | Summary | Evidence | Owner |\n|---|---|---|---|---|---|---|\n| DEF-001 | Sev-3 | open | ACC-IOS-J01 | x | — | — |\n",
      );

      assert.ok(validateRepo(root, { today: TODAY }).errors.some((message) => message.includes("differs from the run record")));
    });

    it("rejects a procedure result that names a different ACTIVE staging environment", () => {
      const mutateProcedures = (text) => {
        const line = text.split("\n").find((entry) => entry.startsWith("| SPR-IOS-01 "));
        const cells = line.split("|");
        cells[4] = " PASS ";
        cells[5] = " Device X, OS 99 ";
        cells[6] = ` ${SHA} `;
        cells[7] = " STG-2 ";
        cells[8] = " observed ";
        cells[9] = ` docs/mvp/qa-evidence/${RUN}/artifacts/ok.png `;
        cells[10] = " none ";
        cells[12] = " tester-1 ";
        cells[13] = " 2026-11-20 ";

        return text.replace(line, cells.join("|"));
      };
      const errors = validateRepo(makeRun({ secondStaging: true, mutateProcedures }), { today: TODAY }).errors;

      assert.ok(errors.some((message) => message.includes("SPR-IOS-01") && message.includes("differs from the run record")), errors.join("\n"));
    });

    it("rejects a VERIFIED run whose own staging identifier is unknown or not ACTIVE", () => {
      const unknown = validateRepo(makeRun({ runStaging: "STG-7", mutate: withStaging("STG-7") }), { today: TODAY }).errors;
      const inactive = validateRepo(makeRun({ stg1Status: "RETIRED", mutate: passJ01 }), { today: TODAY }).errors;

      assert.ok(unknown.some((message) => message.includes('"STG-7" is not an ACTIVE entry')));
      assert.ok(inactive.some((message) => message.includes('"STG-1" is not an ACTIVE entry')));
    });

    describe("isolation line identity is an exact match, not a substring", () => {
      const line = (matched, tail = "corroboration seed marker.") => `Staging isolation: VERIFIED. Fingerprint check artifacts/staging-fingerprint.txt matched ${matched}; ${tail}`;
      const mismatch = (errors, matched, run) => errors.some((message) => message.includes(`matched "${matched}" but the run's staging identifier is "${run}"`));

      it("accepts a line whose matched ID equals the run's ID, including a prefix-like ID", () => {
        assert.deepEqual(validateRepo(makeRun({ secondStaging: true, mutate: passJ01, isolation: line("STG-1") }), { today: TODAY }).errors, []);
        assert.deepEqual(
          validateRepo(makeRun({ tenthStaging: true, runStaging: "STG-10", mutate: withStaging("STG-10"), isolation: line("STG-10") }), { today: TODAY }).errors,
          [],
        );
      });

      it("rejects a line that matched STG-10 for a run on STG-1", () => {
        const errors = validateRepo(makeRun({ tenthStaging: true, mutate: passJ01, isolation: line("STG-10") }), { today: TODAY }).errors;

        assert.ok(mismatch(errors, "STG-10", "STG-1"), errors.join("\n"));
      });

      it("rejects a line that matched STG-1 for a run on STG-10", () => {
        const errors = validateRepo(makeRun({ tenthStaging: true, runStaging: "STG-10", mutate: withStaging("STG-10"), isolation: line("STG-1") }), { today: TODAY }).errors;

        assert.ok(mismatch(errors, "STG-1", "STG-10"), errors.join("\n"));
      });

      it("rejects a line that mentions STG-1 but matched STG-2", () => {
        const isolation = line("STG-2", "corroboration seed marker for STG-1.");
        const errors = validateRepo(makeRun({ secondStaging: true, mutate: passJ01, isolation }), { today: TODAY }).errors;

        assert.ok(mismatch(errors, "STG-2", "STG-1"), errors.join("\n"));
      });

      it("rejects a VERIFIED line that does not follow the documented statement", () => {
        for (const isolation of [
          "Staging isolation: VERIFIED. Fingerprint check passed for STG-1.",
          "Staging isolation: VERIFIED. Fingerprint check artifacts/staging-fingerprint.txt matched STG-1.",
          "Staging isolation: VERIFIED. Fingerprint check matched STG-1; corroboration seed marker.",
          "Staging isolation: VERIFIED. Fingerprint check artifacts/staging-fingerprint.txt matched STG-1; corroboration .",
        ]) {
          const errors = validateRepo(makeRun({ mutate: passJ01, isolation }), { today: TODAY }).errors;

          assert.ok(errors.some((message) => message.includes("a VERIFIED isolation line must read")), `${isolation}\n${errors.join("\n")}`);
        }
      });

      it("extracts only the matched ID from the documented statement", () => {
        assert.equal(parseIsolationMatch(line("STG-10")), "STG-10");
        assert.equal(parseIsolationMatch(line("STG-2", "corroboration saw STG-1 data.")), "STG-2");
        assert.equal(parseIsolationMatch("Staging isolation: NOT VERIFIED. Register not yet approved."), null);
        assert.equal(parseIsolationMatch(undefined), null);
      });
    });
  });

  it("rejects a PASS whose build SHA differs from the run record", () => {
    const root = makeRun({ mutate: (text) => passRow(text, "ACC-IOS-J01", { "App build identifier": "f".repeat(40), "Evidence location": `docs/mvp/qa-evidence/${RUN}/artifacts/ok.png` }) });

    assert.ok(validateRepo(root, { today: TODAY }).errors.some((message) => message.includes("does not match the run record")));
  });
});

describe("repository check", () => {
  it("passes on the committed repository", () => {
    const { errors, summary } = validateRepo(repoRoot, { today: TODAY });

    assert.deepEqual(errors, []);
    assert.ok(summary.some((line) => line === "acceptance template rows: 40"));
    assert.ok(summary.some((line) => line === "procedure result rows: 36"));
  });

  it("rejects a run directory whose record is missing or badly named", () => {
    const root = makeRepo({ runFile: ["docs/mvp/qa-evidence/QA4-20261120-01/notes.md", "x\n"] });

    assert.ok(validateRepo(root, { today: TODAY }).errors.some((message) => message.includes("run-record.md is missing")));

    const badName = makeRepo({ runFile: ["docs/mvp/qa-evidence/run-one/notes.md", "x\n"] });

    assert.ok(validateRepo(badName, { today: TODAY }).errors.some((message) => message.includes("must be named")));
  });
});
