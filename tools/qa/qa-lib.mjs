// Shared logic of the QA-0 evidence validator and the staging fingerprint helper.
// Pure Node (no dependencies). It checks structure and consistency of QA documents;
// it cannot prove that a test was run or that an owner signed. See
// docs/mvp/qa-evidence-and-staging-isolation.md section 9.
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

export const PLATFORMS = { IOS: "iOS", AND: "Android" };
export const JOURNEYS = Array.from({ length: 20 }, (_, i) => `J${String(i + 1).padStart(2, "0")}`);
export const PROCEDURES = Array.from({ length: 18 }, (_, i) => `SP-${String(i + 1).padStart(2, "0")}`);

export const ROW_FIELDS = [
  "Row ID",
  "Journey",
  "Platform",
  "Title",
  "Preconditions",
  "Test actions",
  "Expected API outcome",
  "Expected UI outcome",
  "Financial invariants",
  "Device model and OS",
  "App build identifier",
  "Staging environment identifier",
  "Actual result",
  "Evidence location",
  "Defect reference",
  "Blocker reference",
  "Tester",
  "Execution date",
  "Status",
  "Waiver reference",
];
const SPEC_FIELDS = ROW_FIELDS.slice(0, 9);

export const SP_COLUMNS = [
  "Result ID",
  "Procedure",
  "Platform",
  "Status",
  "Device model and OS",
  "App build identifier",
  "Staging environment identifier",
  "Actual result",
  "Evidence location",
  "Defect reference",
  "Blocker reference",
  "Tester",
  "Execution date",
];

export const STATUSES = ["NOT RUN", "PASS", "FAIL", "BLOCKED", "WAIVED"];
const EVIDENCE_ROOT = "docs/mvp/qa-evidence/";
const SHA40 = /\b[0-9a-f]{40}\b/;
const FINGERPRINT = /^fp1:[0-9a-f]{16}$/;

// Lowest OS versions that Expo SDK 57 / React Native 0.86.3 allow (QA-0 verification).
export const FLOORS = { ios: [16, 4], androidApi: 24 };

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export const isBlank = (value) => value === undefined || value === "" || value === "—" || value === "-";
const isTbd = (value) => /^TBD\b/i.test(value ?? "");

// ------------------------------------------------------------------ parsing

// Denylist entries the owner has recorded: a valid fingerprint, who recorded it and when.
export function approvedDenylist(denylist) {
  return denylist.filter(
    (row) => FINGERPRINT.test(row.Fingerprint ?? "") && !isBlank(row["Recorded by"]) && ISO_DATE.test(row["Recorded on"] ?? ""),
  );
}

// Platforms a waiver covers, from its "Platforms" cell (for example "iOS; Android").
export function parseWaiverPlatforms(value) {
  const platforms = new Set();
  const invalid = [];

  for (const token of (value ?? "").split(/[;,/]|\band\b/i).map((part) => part.trim()).filter((part) => part !== "")) {
    if (/^ios$/i.test(token)) {
      platforms.add(PLATFORMS.IOS);
    } else if (/^android$/i.test(token)) {
      platforms.add(PLATFORMS.AND);
    } else {
      invalid.push(token);
    }
  }

  return { platforms, invalid };
}

export function splitRow(line) {
  const trimmed = line.trim();

  if (!trimmed.startsWith("|")) {
    return null;
  }

  const cells = trimmed.replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());

  return cells.every((cell) => /^:?-{3,}:?$/.test(cell)) ? null : cells;
}

// A "#### ACC-..." heading followed by a two-column Field | Value table.
export function parseRowBlocks(text) {
  const lines = text.split(/\r?\n/);
  const blocks = [];
  let current = null;

  for (const line of lines) {
    const heading = /^####\s+(ACC-[A-Z]+-J\d+)\b/.exec(line);

    if (heading) {
      current = { heading: heading[1], fields: new Map(), order: [], duplicates: [] };
      blocks.push(current);
      continue;
    }

    if (/^#{1,4}\s/.test(line)) {
      current = null;
      continue;
    }

    if (current === null) {
      continue;
    }

    const cells = splitRow(line);

    if (cells === null || cells.length < 2 || cells[0] === "Field") {
      continue;
    }

    const [name, ...rest] = cells;
    const value = rest.join("|");

    if (current.fields.has(name)) {
      current.duplicates.push(name);
    }

    current.fields.set(name, value);
    current.order.push(name);
  }

  return blocks;
}

// Rows of the first table that follows a heading containing `title`, keyed by header cells.
export function parseTableUnder(text, title) {
  const lines = text.split(/\r?\n/);
  const headingText = (line) => line.replace(/^#{1,6}\s+/, "").replace(/^\d+(\.\d+)*\.?\s+/, "").trim();
  const isHeading = (line) => /^#{1,6}\s/.test(line);
  // An exact heading wins over one that merely contains the title (for example "# Waiver Register (QA-0)").
  let start = lines.findIndex((line) => isHeading(line) && headingText(line) === title);

  if (start === -1) {
    start = lines.findIndex((line) => isHeading(line) && line.includes(title));
  }

  if (start === -1) {
    return null;
  }

  let header = null;
  const rows = [];

  for (let i = start + 1; i < lines.length; i++) {
    if (/^#{1,6}\s/.test(lines[i])) {
      break;
    }

    const cells = splitRow(lines[i]);

    if (cells === null) {
      continue;
    }

    if (header === null) {
      header = cells;
      continue;
    }

    if (cells[0].startsWith("(")) {
      continue;
    }

    rows.push(Object.fromEntries(header.map((name, index) => [name, cells[index] ?? ""])));
  }

  return { header: header ?? [], rows };
}

export function parseStagingRegister(text) {
  const staging = parseTableUnder(text, "Staging environments");
  const denylist = parseTableUnder(text, "Production denylist");

  return { staging: staging?.rows ?? [], denylist: denylist?.rows ?? [], hasTables: staging !== null && denylist !== null };
}

export function parseWaivers(text) {
  return parseTableUnder(text, "Register")?.rows ?? [];
}

export function parseDefects(text) {
  const table = parseTableUnder(text, "Defects") ?? parseTableUnder(text, "Defect");

  return new Map((table?.rows ?? []).map((row) => [row["Defect ID"], row]));
}

// ----------------------------------------------------------------- fingerprint

// One-way fingerprint of an origin. Path, query, credentials and default ports are dropped.
export function originFingerprint(rawUrl) {
  let url;

  try {
    url = new URL(rawUrl);
  } catch {
    return null;
  }

  if (url.protocol !== "https:" && url.protocol !== "http:") {
    return null;
  }

  const port = url.port && !(url.protocol === "https:" && url.port === "443") && !(url.protocol === "http:" && url.port === "80") ? `:${url.port}` : "";
  const origin = `${url.protocol}//${url.hostname.toLowerCase()}${port}`;

  return `fp1:${createHash("sha256").update(origin).digest("hex").slice(0, 16)}`;
}

// ---------------------------------------------------------------- row checking

function evidencePaths(value) {
  return value
    .split(/<br>|;|,/)
    .map((part) => part.replace(/`/g, "").trim())
    .filter((part) => !isBlank(part));
}

function isRealDate(value, today) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return false;
  }

  const date = new Date(`${value}T00:00:00Z`);

  return !Number.isNaN(date.getTime()) && date.toISOString().startsWith(value) && value <= today;
}

function defectIds(value) {
  return value.split(/[;,\s]+/).filter((part) => part !== "" && part !== "—");
}

/**
 * Status rules shared by journey rows and procedure rows.
 * `v` maps field name to value; `ctx` supplies the registers and file lookup.
 */
export function checkResult(label, v, ctx) {
  const errors = [];
  const fail = (message) => errors.push(`${label}: ${message}`);
  const status = v.Status;

  if (!STATUSES.includes(status)) {
    fail(`Status "${status}" is not one of ${STATUSES.join(", ")}`);
    return errors;
  }

  const isProcedure = v.journey === null;
  const waiverRef = v["Waiver reference"];

  if (status !== "WAIVED" && waiverRef !== undefined && !isBlank(waiverRef)) {
    fail("a Waiver reference is only allowed on a WAIVED row");
  }

  if (status === "NOT RUN") {
    for (const name of ["Actual result", "Evidence location", "Tester", "Execution date", "Defect reference"]) {
      if (!isBlank(v[name])) {
        fail(`NOT RUN row must leave "${name}" as —`);
      }
    }

    return errors;
  }

  if (status === "BLOCKED") {
    if (isBlank(v["Actual result"])) {
      fail("BLOCKED needs an Actual result that states the reason");
    }

    if (isBlank(v["Blocker reference"])) {
      fail("BLOCKED needs a Blocker reference");
    }

    return errors;
  }

  if (status === "WAIVED") {
    if (isProcedure || v.journey !== "J18") {
      fail("only J18 may be WAIVED (BR-5, GAP-20); every other row must be executed or BLOCKED");
    }

    const waiver = ctx.waivers?.find((entry) => entry["Waiver ID"] === waiverRef);

    if (isBlank(waiverRef) || !/^WAIVER-J18-\d+$/.test(waiverRef ?? "")) {
      fail("WAIVED needs a Waiver reference of the form WAIVER-J18-<n>");
    } else if (!waiver) {
      fail(`Waiver reference ${waiverRef} is not in the waiver register`);
    } else {
      const required = ["Journey", "Authority", "Platforms", "Waived element", "Reason", "Owner", "Signed on", "Decision record reference"];

      if (waiver.Status !== "SIGNED") {
        fail(`waiver ${waiverRef} is not SIGNED by the owner`);
      }

      for (const name of required) {
        if (isBlank(waiver[name])) {
          fail(`waiver ${waiverRef} has no "${name}"`);
        }
      }

      if (waiver.Journey !== "J18") {
        fail(`waiver ${waiverRef} is not for J18`);
      }

      const covered = parseWaiverPlatforms(waiver.Platforms);

      if (covered.invalid.length > 0 || covered.platforms.size === 0) {
        fail(`waiver ${waiverRef} must list its platforms as iOS, Android or "iOS; Android"`);
      } else if (!isProcedure && !covered.platforms.has(v.Platform)) {
        fail(`waiver ${waiverRef} covers ${[...covered.platforms].join(" and ")} but this row is ${v.Platform}`);
      }

      if (!isBlank(waiver["Signed on"]) && !isRealDate(waiver["Signed on"], ctx.today)) {
        fail(`waiver ${waiverRef} has an invalid signing date`);
      }
    }

    if (isBlank(v["Actual result"])) {
      fail("WAIVED needs an Actual result that records what was waived");
    }

    return errors;
  }

  // PASS and FAIL: both assert that the row was executed on a device.
  for (const name of ["Device model and OS", "App build identifier", "Staging environment identifier"]) {
    if (isBlank(v[name]) || isTbd(v[name])) {
      fail(`${status} needs "${name}"`);
    }
  }

  const build = v["App build identifier"] ?? "";
  const sha = SHA40.exec(build)?.[0];

  if (!sha) {
    fail(`${status} needs the full 40-character commit SHA in "App build identifier"`);
  } else if (ctx.appSha && sha !== ctx.appSha) {
    fail("App build identifier does not match the run record's App commit SHA");
  }

  const stagingId = v["Staging environment identifier"];
  const entry = ctx.staging?.find((candidate) => candidate["Staging ID"] === stagingId);

  if (ctx.staging && !entry) {
    fail(`staging identifier "${stagingId}" is not in the staging register`);
  } else if (entry && entry.Status !== "ACTIVE") {
    fail(`staging identifier "${stagingId}" is not ACTIVE`);
  }

  if (ctx.runStagingId !== undefined && stagingId !== ctx.runStagingId) {
    fail(`staging identifier "${stagingId}" differs from the run record's "${ctx.runStagingId}"`);
  }

  if (ctx.denylistApproved === false) {
    fail(`${status} is not allowed: the staging register has no owner-approved production denylist entry`);
  }

  if (ctx.isolationVerified === false) {
    fail(`${status} is not allowed: the run record does not carry "Staging isolation: VERIFIED"`);
  }

  if (isBlank(v["Actual result"])) {
    fail(`${status} needs an Actual result`);
  }

  if (isBlank(v.Tester)) {
    fail(`${status} needs a Tester`);
  }

  if (!isRealDate(v["Execution date"] ?? "", ctx.today)) {
    fail(`${status} needs an Execution date (YYYY-MM-DD, not in the future)`);
  }

  const evidence = evidencePaths(v["Evidence location"] ?? "");

  if (evidence.length === 0) {
    fail(`${status} needs an Evidence location`);
  }

  for (const path of evidence) {
    if (!path.startsWith(EVIDENCE_ROOT) || path.includes("..") || path.includes("\\")) {
      fail(`evidence "${path}" must be a file path under ${EVIDENCE_ROOT}`);
    } else if (!ctx.fileExists(path)) {
      fail(`evidence file "${path}" does not exist`);
    }
  }

  const defectField = v["Defect reference"] ?? "";
  const ids = defectIds(defectField);

  if (status === "PASS") {
    if (isBlank(defectField) || (ids.length === 1 && ids[0].toLowerCase() === "none")) {
      // fine: no defect recorded
    } else {
      for (const id of ids) {
        const defect = ctx.defects?.get(id);

        if (!/^DEF-\d{3,}$/.test(id)) {
          fail(`defect reference "${id}" must be "none" or DEF-<nnn>`);
        } else if (!defect) {
          fail(`defect ${id} is not in the run's defect register`);
        } else if (defect.Status === "open" && !/^Sev-[34]$/.test(defect.Severity)) {
          fail(`PASS cannot reference open ${defect.Severity} defect ${id}`);
        }
      }
    }
  }

  if (status === "FAIL") {
    if (ids.length === 0 || ids.every((id) => id.toLowerCase() === "none")) {
      fail("FAIL needs a Defect reference");
    }

    for (const id of ids) {
      if (!/^DEF-\d{3,}$/.test(id)) {
        fail(`defect reference "${id}" must be DEF-<nnn>`);
      } else if (ctx.defects && !ctx.defects.has(id)) {
        fail(`defect ${id} is not in the run's defect register`);
      }
    }
  }

  return errors;
}

// ------------------------------------------------------------ document checks

/**
 * Journey acceptance document (blank template or a run copy).
 * mode "template": every row must be blank (NOT RUN, or BLOCKED with a blocker).
 */
export function checkAcceptance(text, ctx, mode) {
  const errors = [];
  const blocks = parseRowBlocks(text);
  const seen = new Set();
  const perPlatform = { IOS: new Set(), AND: new Set() };

  for (const block of blocks) {
    const label = block.heading;
    const match = /^ACC-(IOS|AND)-(J\d{2})$/.exec(block.heading);

    if (!match) {
      errors.push(`${label}: heading is not ACC-<IOS|AND>-J<nn>`);
      continue;
    }

    const [, platformKey, journey] = match;

    if (seen.has(block.heading)) {
      errors.push(`${label}: duplicate journey/platform row`);
    }

    seen.add(block.heading);

    if (!JOURNEYS.includes(journey)) {
      errors.push(`${label}: ${journey} is outside J01–J20`);
    } else {
      perPlatform[platformKey].add(journey);
    }

    for (const duplicate of block.duplicates) {
      errors.push(`${label}: field "${duplicate}" appears more than once`);
    }

    for (const name of ROW_FIELDS) {
      if (!block.fields.has(name)) {
        errors.push(`${label}: missing mandatory field "${name}"`);
      }
    }

    for (const name of block.order) {
      if (!ROW_FIELDS.includes(name)) {
        errors.push(`${label}: unknown field "${name}"`);
      }
    }

    if (block.order.join("|") !== ROW_FIELDS.join("|") && block.duplicates.length === 0 && ROW_FIELDS.every((name) => block.fields.has(name)) && block.order.length === ROW_FIELDS.length) {
      errors.push(`${label}: fields are not in the standard order`);
    }

    const v = Object.fromEntries(block.fields);

    if (v["Row ID"] !== block.heading) {
      errors.push(`${label}: Row ID "${v["Row ID"]}" does not match the heading`);
    }

    if (v.Journey !== journey) {
      errors.push(`${label}: Journey field "${v.Journey}" does not match the row`);
    }

    if (v.Platform !== PLATFORMS[platformKey]) {
      errors.push(`${label}: Platform field "${v.Platform}" does not match the row`);
    }

    for (const name of SPEC_FIELDS) {
      if (isBlank(v[name])) {
        errors.push(`${label}: mandatory field "${name}" is empty`);
      }
    }

    if (mode === "template" && !["NOT RUN", "BLOCKED"].includes(v.Status)) {
      errors.push(`${label}: the blank template may contain only NOT RUN or BLOCKED rows, found "${v.Status}"`);
    }

    errors.push(...checkResult(label, { ...v, journey }, ctx));
  }

  for (const [key, name] of Object.entries(PLATFORMS)) {
    const missing = JOURNEYS.filter((journey) => !perPlatform[key].has(journey));

    if (missing.length > 0) {
      errors.push(`${name}: missing journeys ${missing.join(", ")}`);
    }
  }

  if (blocks.length !== 40) {
    errors.push(`expected exactly 40 journey/platform rows, found ${blocks.length}`);
  }

  return errors;
}

// Procedure results table (SP-01..SP-18 on both platforms).
export function checkProcedures(text, ctx, mode) {
  const errors = [];
  const table = parseTableUnder(text, "Procedure results");

  if (table === null) {
    return ["no 'Procedure results' table found"];
  }

  if (table.header.join("|") !== SP_COLUMNS.join("|")) {
    errors.push(`procedure results columns must be exactly: ${SP_COLUMNS.join(" | ")}`);
    return errors;
  }

  const seen = new Set();

  for (const row of table.rows) {
    const label = row["Result ID"];
    const key = `${row.Procedure}/${row.Platform}`;

    if (seen.has(key)) {
      errors.push(`${label}: duplicate procedure/platform row ${key}`);
    }

    seen.add(key);

    if (!PROCEDURES.includes(row.Procedure)) {
      errors.push(`${label}: ${row.Procedure} is not SP-01..SP-18`);
    }

    if (!Object.values(PLATFORMS).includes(row.Platform)) {
      errors.push(`${label}: unknown platform "${row.Platform}"`);
    }

    if (row.Status === "WAIVED") {
      errors.push(`${label}: procedures cannot be WAIVED`);
    }

    if (mode === "template" && !["NOT RUN", "BLOCKED"].includes(row.Status)) {
      errors.push(`${label}: the blank template may contain only NOT RUN or BLOCKED rows`);
    }

    errors.push(...checkResult(label, { ...row, journey: null, "Waiver reference": undefined }, ctx));
  }

  for (const procedure of PROCEDURES) {
    for (const platform of Object.values(PLATFORMS)) {
      if (!seen.has(`${procedure}/${platform}`)) {
        errors.push(`missing procedure result ${procedure} on ${platform}`);
      }
    }
  }

  if (table.rows.length !== PROCEDURES.length * 2) {
    errors.push(`expected ${PROCEDURES.length * 2} procedure result rows, found ${table.rows.length}`);
  }

  return errors;
}

export function checkStagingRegister(text) {
  const errors = [];
  const { staging, denylist, hasTables } = parseStagingRegister(text);

  if (!hasTables) {
    return ["staging register must have 'Staging environments' and 'Production denylist' tables"];
  }

  const stagingPrints = new Set();

  for (const entry of staging) {
    if (entry.Status !== "ACTIVE") {
      continue;
    }

    for (const name of ["API origin fingerprint", "Auth project fingerprint", "Database host fingerprint"]) {
      if (!FINGERPRINT.test(entry[name] ?? "")) {
        errors.push(`${entry["Staging ID"]}: "${name}" must be fp1:<16 hex>`);
      } else {
        stagingPrints.add(entry[name]);
      }
    }

    for (const name of ["Approved by", "Approved on"]) {
      if (isBlank(entry[name])) {
        errors.push(`${entry["Staging ID"]}: ACTIVE needs "${name}" (owner approval)`);
      }
    }
  }

  for (const entry of denylist) {
    if (!FINGERPRINT.test(entry.Fingerprint ?? "")) {
      errors.push(`denylist entry "${entry.Fingerprint}" must be fp1:<16 hex>`);
    } else if (stagingPrints.has(entry.Fingerprint)) {
      errors.push(`fingerprint ${entry.Fingerprint} is both ACTIVE staging and on the production denylist`);
    } else if (!approvedDenylist([entry]).length) {
      errors.push(`denylist entry ${entry.Fingerprint} needs "Recorded by" and a "Recorded on" date (owner approval)`);
    }
  }

  // A staging match proves nothing about production unless the owner has said what production looks like.
  if (staging.some((entry) => entry.Status === "ACTIVE") && approvedDenylist(denylist).length === 0) {
    errors.push("an ACTIVE staging entry requires at least one owner-approved production denylist entry (fingerprint, Recorded by, Recorded on)");
  }

  return errors;
}

// Documented VERIFIED statement: "Staging isolation: VERIFIED. Fingerprint check <artifact path> matched <STG id>;
// corroboration <list>." Returns the matched environment ID, or null when the line does not follow that shape.
// The ID is compared by equality; a substring test would let STG-1 match a line that matched STG-10 or STG-2.
const VERIFIED_LINE = /^Staging isolation: VERIFIED\. Fingerprint check (\S+) matched ([^\s;]+); corroboration (\S.*)\.$/;

export function parseIsolationMatch(line) {
  const match = VERIFIED_LINE.exec(line ?? "");

  return match ? match[2] : null;
}

export function checkRunRecord(text, runId) {
  const errors = [];
  const fields = new Map();

  for (const line of text.split(/\r?\n/)) {
    const cells = splitRow(line);

    if (cells && cells.length >= 2 && cells[0] !== "Field") {
      fields.set(cells[0], cells.slice(1).join("|"));
    }
  }

  const required = [
    "Run ID", "Gate and scope", "App commit SHA", "Backend commit SHA", "Backend migration head", "App version",
    "Build type", "Build channel", "Installation method", "Staging environment identifier", "Staging isolation line",
    "Devices", "Network profile", "Accessibility settings", "Test users", "Tester", "Started and finished", "Owner sign-off",
  ];

  for (const name of required) {
    if (isBlank(fields.get(name))) {
      errors.push(`run record: missing "${name}"`);
    }
  }

  if (fields.get("Run ID") !== runId) {
    errors.push(`run record: Run ID "${fields.get("Run ID")}" does not match directory ${runId}`);
  }

  for (const name of ["App commit SHA", "Backend commit SHA"]) {
    if (!isBlank(fields.get(name)) && !/^[0-9a-f]{40}$/.test(fields.get(name))) {
      errors.push(`run record: "${name}" must be a full 40-character SHA`);
    }
  }

  if (!["expo-go", "development-build", "internal-release"].includes(fields.get("Build type"))) {
    errors.push("run record: Build type must be expo-go, development-build or internal-release");
  }

  const line = fields.get("Staging isolation line") ?? "";
  const verified = /^Staging isolation: VERIFIED\./.test(line);
  const notVerified = /^Staging isolation: NOT VERIFIED\./.test(line);

  if (!verified && !notVerified) {
    errors.push('run record: "Staging isolation line" must start with "Staging isolation: VERIFIED." or "Staging isolation: NOT VERIFIED."');
  }

  return {
    errors,
    isolationVerified: verified,
    isolationLine: line,
    appSha: /^[0-9a-f]{40}$/.test(fields.get("App commit SHA") ?? "") ? fields.get("App commit SHA") : undefined,
    stagingId: fields.get("Staging environment identifier"),
  };
}

// ---------------------------------------------------------------- text scans

const ALLOWED_URL_HOSTS = new Set([
  "docs.expo.dev",
  "github.com",
  "developer.apple.com",
  "developer.android.com",
  "reactnative.dev",
  "example.test",
  "example.invalid",
]);
const ALLOWED_EMAIL_DOMAINS = new Set(["example.test", "example.invalid"]);

export const SECRET_PATTERNS = [
  ["JSON Web Token", /\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/],
  ["Supabase key", /\bsb_(publishable|secret)_[A-Za-z0-9_-]{8,}/],
  ["service role value", /service_role["']?\s*[:=]\s*["']?[A-Za-z0-9._-]{20,}/i],
  ["bearer token", /\bBearer\s+[A-Za-z0-9._~+/=-]{20,}/],
  ["database URL with credentials", /\b(?:postgres(?:ql)?|mysql)(?:\+\w+)?:\/\/[^\s:@/]+:[^\s@/]+@/i],
  ["hosted back-end hostname", /\b[a-z0-9-]+\.(?:supabase\.(?:co|in)|onrender\.com|herokuapp\.com|ngrok(?:-free)?\.(?:app|io))\b/i],
  ["private network address", /\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b/],
];

export function scanForSecrets(text) {
  const findings = [];

  for (const [name, pattern] of SECRET_PATTERNS) {
    if (pattern.test(text)) {
      findings.push(`${name} pattern`);
    }
  }

  for (const match of text.matchAll(/https?:\/\/([^\s/?#)>\]"'`]+)/g)) {
    const authority = match[1];

    // A template placeholder such as ${host} is source code, not an endpoint.
    if (/[${}]/.test(authority)) {
      continue;
    }

    if (authority.includes("@")) {
      findings.push("URL with embedded credentials");
    }

    const host = authority.slice(authority.lastIndexOf("@") + 1).replace(/:\d+$/, "").toLowerCase();
    const placeholder = host.endsWith(".example.test") || host.endsWith(".example.invalid");

    if (!ALLOWED_URL_HOSTS.has(host) && !placeholder) {
      findings.push(`URL to non-allowlisted host "${host}"`);
    }
  }

  for (const match of text.matchAll(/[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})/g)) {
    if (!ALLOWED_EMAIL_DOMAINS.has(match[1].toLowerCase())) {
      findings.push(`email address on non-example domain "${match[1]}"`);
    }
  }

  return [...new Set(findings)];
}

const STALE_MARKER = /QA-0 (superseded|exception)/i;

// Mentions of an iOS or Android minimum below the pinned floors.
export function findStaleFloors(text) {
  const hits = [];

  text.split(/\r?\n/).forEach((line, index) => {
    if (STALE_MARKER.test(line)) {
      return;
    }

    for (const match of line.matchAll(/\biOS\s*(\d+)(?:\.(\d+))?\b/gi)) {
      const major = Number(match[1]);
      const minor = Number(match[2] ?? 0);

      // iOS 26.x is the current OS naming; only versions below the floor are stale.
      if (major < FLOORS.ios[0] || (major === FLOORS.ios[0] && minor < FLOORS.ios[1])) {
        hits.push({ line: index + 1, text: line.trim().slice(0, 120), what: `iOS ${match[1]}${match[2] ? `.${match[2]}` : ""}` });
      }
    }

    for (const match of line.matchAll(/\b(?:Android\s+API|API\s+level|minSdk(?:Version)?)\s*[=:]?\s*"?(\d+)\b/gi)) {
      if (Number(match[1]) < FLOORS.androidApi) {
        hits.push({ line: index + 1, text: line.trim().slice(0, 120), what: `Android API ${match[1]}` });
      }
    }
  });

  return hits;
}

// ---------------------------------------------------------------- repository

function walk(directory, accept, root, out = []) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    if (["node_modules", ".git", ".expo", "dist", "build"].includes(entry.name)) {
      continue;
    }

    const path = join(directory, entry.name);

    if (entry.isDirectory()) {
      walk(path, accept, root, out);
    } else if (accept(relative(root, path).split(sep).join("/"))) {
      out.push(path);
    }
  }

  return out;
}

const RUN_ID = /^QA\d+-\d{8}-\d{2}$/;
const read = (path) => readFileSync(path, "utf8");

/**
 * Validates a checkout. Returns { errors, summary }.
 * `today` (YYYY-MM-DD) is injectable for tests.
 */
export function validateRepo(root, { today = new Date().toISOString().slice(0, 10) } = {}) {
  const errors = [];
  const summary = [];
  const fileExists = (path) => {
    const full = join(root, path);

    return existsSync(full) && statSync(full).isFile();
  };
  const evidenceDir = join(root, "docs/mvp/qa-evidence");

  const registerPath = join(evidenceDir, "staging-register.md");
  const waiverPath = join(evidenceDir, "waivers.md");
  const registerText = existsSync(registerPath) ? read(registerPath) : null;
  const waiverText = existsSync(waiverPath) ? read(waiverPath) : null;

  if (registerText === null) {
    errors.push("docs/mvp/qa-evidence/staging-register.md is missing");
  }

  if (waiverText === null) {
    errors.push("docs/mvp/qa-evidence/waivers.md is missing");
  }

  const register = registerText === null ? { staging: [], denylist: [] } : parseStagingRegister(registerText);
  const waivers = waiverText === null ? [] : parseWaivers(waiverText);
  const denylistApproved = approvedDenylist(register.denylist).length > 0;
  const baseCtx = { today, fileExists, staging: register.staging, waivers, denylistApproved };

  if (registerText !== null) {
    errors.push(...checkStagingRegister(registerText).map((message) => `staging-register.md: ${message}`));
  }

  for (const waiver of waivers) {
    if (waiver.Status === "SIGNED" && waiver.Journey !== "J18") {
      errors.push(`waivers.md: ${waiver["Waiver ID"]} is signed for ${waiver.Journey}; only J18 may be waived`);
    }
  }

  const templatePath = join(root, "docs/mvp/qa-device-acceptance-template.md");
  const proceduresPath = join(root, "docs/mvp/qa-security-regression-procedures.md");

  if (existsSync(templatePath)) {
    const templateText = read(templatePath);
    const found = checkAcceptance(templateText, baseCtx, "template");

    errors.push(...found.map((message) => `qa-device-acceptance-template.md: ${message}`));
    summary.push(`acceptance template rows: ${parseRowBlocks(templateText).length}`);
  } else {
    errors.push("docs/mvp/qa-device-acceptance-template.md is missing");
  }

  if (existsSync(proceduresPath)) {
    const procedureText = read(proceduresPath);

    errors.push(...checkProcedures(procedureText, baseCtx, "template").map((message) => `qa-security-regression-procedures.md: ${message}`));
    summary.push(`procedure result rows: ${parseTableUnder(procedureText, "Procedure results")?.rows.length ?? 0}`);
  } else {
    errors.push("docs/mvp/qa-security-regression-procedures.md is missing");
  }

  // Run copies.
  let runs = 0;

  if (existsSync(evidenceDir)) {
    for (const entry of readdirSync(evidenceDir, { withFileTypes: true })) {
      if (!entry.isDirectory()) {
        continue;
      }

      if (!RUN_ID.test(entry.name)) {
        errors.push(`qa-evidence/${entry.name}: run directory must be named QA<n>-YYYYMMDD-NN`);
        continue;
      }

      runs += 1;
      const dir = join(evidenceDir, entry.name);
      const label = `qa-evidence/${entry.name}`;
      const recordPath = join(dir, "run-record.md");

      if (!existsSync(recordPath)) {
        errors.push(`${label}: run-record.md is missing`);
        continue;
      }

      const record = checkRunRecord(read(recordPath), entry.name);

      errors.push(...record.errors.map((message) => `${label}: ${message}`));

      const runStagingId = isBlank(record.stagingId) ? undefined : record.stagingId;

      if (record.isolationVerified) {
        const runStaging = register.staging.find((entry) => entry["Staging ID"] === runStagingId);

        if (!runStaging || runStaging.Status !== "ACTIVE") {
          errors.push(`${label}: run record staging identifier "${runStagingId}" is not an ACTIVE entry of the staging register`);
        } else {
          const matched = parseIsolationMatch(record.isolationLine);

          if (matched === null) {
            errors.push(`${label}: a VERIFIED isolation line must read "Staging isolation: VERIFIED. Fingerprint check <artifact path> matched <STG id>; corroboration <list>."`);
          } else if (matched !== runStagingId) {
            errors.push(`${label}: the isolation line matched "${matched}" but the run's staging identifier is "${runStagingId}"`);
          }
        }

        if (!denylistApproved) {
          errors.push(`${label}: "Staging isolation: VERIFIED" is not allowed while the register has no owner-approved production denylist entry`);
        }
      }

      const defectsPath = join(dir, "defects.md");
      const ctx = {
        ...baseCtx,
        appSha: record.appSha,
        runStagingId,
        isolationVerified: record.isolationVerified,
        defects: existsSync(defectsPath) ? parseDefects(read(defectsPath)) : new Map(),
      };

      for (const [file, check] of [["acceptance.md", checkAcceptance], ["procedures.md", checkProcedures]]) {
        const path = join(dir, file);

        if (!existsSync(path)) {
          errors.push(`${label}: ${file} is missing`);
        } else {
          errors.push(...check(read(path), ctx, "run").map((message) => `${label}/${file}: ${message}`));
        }
      }
    }
  }

  summary.push(`run records: ${runs}`);

  // Text scans over QA files and every text file of a run.
  const qaFiles = walk(
    root,
    (path) =>
      /^docs\/mvp\/qa-[^/]+\.md$/.test(path) ||
      /^docs\/mvp\/qa-evidence\/.+\.(md|txt|json|csv|log)$/.test(path) ||
      /^tools\/qa\/[^/]+\.mjs$/.test(path),
    root,
  );

  for (const file of qaFiles) {
    for (const finding of scanForSecrets(read(file))) {
      errors.push(`${relative(root, file)}: ${finding} (no production endpoint, token or credential may be committed)`);
    }
  }

  summary.push(`QA files scanned for secrets and endpoints: ${qaFiles.length}`);

  // Stale OS floors anywhere in tracked documentation.
  const docs = walk(root, (path) => /\.md$/.test(path) && !path.startsWith("services/") && !path.startsWith("node_modules/"), root);

  for (const file of docs) {
    for (const hit of findStaleFloors(read(file))) {
      errors.push(`${relative(root, file)}:${hit.line}: stale OS floor "${hit.what}" without a QA-0 exception or superseded note: ${hit.text}`);
    }
  }

  summary.push(`Markdown files checked for stale OS floors: ${docs.length}`);

  return { errors, summary };
}
