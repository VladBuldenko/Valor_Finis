// VF-020F4: wiring, retry, accessibility and boundary checks on the screens.
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, "..", "..");
const APP = join(HERE, "../../../app");
const read = (...parts: string[]) => readFileSync(join(...parts), "utf8");
const screens = ["inbox-screen.tsx", "proposal-detail-screen.tsx", "alerts-screen.tsx"];

describe("routes and navigation", () => {
  it("the three routes exist, are thin and are registered", () => {
    const routes: [string, RegExp][] = [
      ["(app)/inbox/index.tsx", /InboxScreen/],
      ["(app)/inbox/proposals/[id].tsx", /ProposalDetailScreen/],
      ["(app)/inbox/alerts.tsx", /AlertsScreen/],
    ];

    for (const [file, pattern] of routes) {
      assert.match(read(APP, file), pattern, file);
    }

    const layout = read(APP, "(app)/_layout.tsx");

    for (const name of ["inbox/index", "inbox/proposals/[id]", "inbox/alerts"]) {
      assert.ok(layout.includes(`name="${name}"`), name);
    }
  });
});

describe("independent sources and per-source Retry", () => {
  const inbox = read(HERE, "inbox-screen.tsx");

  it("each of the three sections has its own error branch and its own Retry bound to its own query", () => {
    assert.match(inbox, /proposals\.isError[\s\S]*?proposals\.refetch\(\)/);
    assert.match(inbox, /alerts\.isError[\s\S]*?alerts\.refetch\(\)/);
    assert.match(inbox, /executions\.isError[\s\S]*?executions\.refetch\(\)/);
    assert.equal((inbox.match(/<SectionRetry/g) ?? []).length, 3);
  });

  it("a section's error never replaces another section (no early return before the one render path)", () => {
    const body = inbox.slice(inbox.indexOf("export function InboxScreen"));
    const beforeRender = body.slice(0, body.indexOf("return ("));

    assert.doesNotMatch(beforeRender, /isError|isLoading|return/);
  });

  it("alerts unavailable is its own message, not the empty state", () => {
    assert.match(inbox, /alertsUnavailable \? <Text[^>]*>\{COPY\.alertsUnavailable\}/);
    assert.match(inbox, /!alertsUnavailable && alertItems\.length === 0/);
  });

  it("recent activity is informational: no link or action on an execution row; the only navigation is the section's 'See all activity' link to the history (VF-020F6)", () => {
    const section = inbox.slice(inbox.indexOf("Recent activity"));
    const rows = section.slice(section.indexOf(".map("), section.indexOf("</ScrollView>"));
    const rowsOnly = rows.slice(0, rows.indexOf('<Link href="/rules/history"'));

    assert.doesNotMatch(rowsOnly, /<Link|<Pressable|onPress/);
    assert.equal((section.match(/<Link/g) ?? []).length, 1);
    assert.equal((section.match(/<Pressable/g) ?? []).length, 1);
    assert.doesNotMatch(section, /onPress/);
    assert.match(section, /<Link href="\/rules\/history" asChild>[\s\S]*?See all activity/);
  });

  it("opens the Inbox with an evaluation request", () => {
    assert.match(inbox, /request\("inbox_open"\)/);
  });
});

describe("evaluation mounting", () => {
  it("the host is mounted once, in the root layout, inside the session scope", () => {
    const layout = read(APP, "_layout.tsx");

    assert.equal((layout.match(/<RulesEvaluationHost>/g) ?? []).length, 1);
    assert.ok(layout.indexOf("<SessionScope") < layout.indexOf("<RulesEvaluationHost>"));
  });

  it("only the host listens to AppState for rules; no screen calls evaluate directly", () => {
    const offenders: string[] = [];
    const walk = (dir: string) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const path = join(dir, entry.name);

        if (entry.isDirectory()) walk(path);
        else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\./.test(entry.name)) {
          const source = readFileSync(path, "utf8");

          if (/AppState\.addEventListener/.test(source) && !/supabase\.ts$|rules-evaluation-host\.tsx$/.test(path)) offenders.push(path);
          if (/evaluateRules\(/.test(source) && !/financial-rule\.(api|service)|rules-evaluation-host\.tsx$/.test(path)) offenders.push(path);
        }
      }
    };

    walk(SRC);
    assert.deepEqual(offenders, []);
  });

  it("Income create asks for an evaluation only after a successful create", () => {
    const income = read(SRC, "features/income/income-create-screen.tsx");
    const onSuccess = income.slice(income.indexOf("onSuccess"), income.indexOf("onError"));

    assert.match(onSuccess, /requestRulesEvaluation\("income_recorded"\)/);
    assert.doesNotMatch(income.slice(income.indexOf("onError")), /requestRulesEvaluation/);
  });
});

describe("accessibility, copy and boundaries", () => {
  it("every Pressable declares an accessibilityRole", () => {
    for (const name of screens) {
      const source = read(HERE, name);

      for (const match of source.matchAll(/<Pressable\b/g)) {
        const end = source.indexOf("</Pressable>", match.index);
        const block = source.slice(match.index, end === -1 ? undefined : end);

        assert.match(block.slice(0, 900), /accessibilityRole=/, `${name} @${match.index}`);
      }
    }
  });

  it("decisions require a dialog and a single in-flight request", () => {
    const detail = read(HERE, "proposal-detail-screen.tsx");

    assert.match(detail, /Alert\.alert\(dialog\.title/);
    assert.match(detail, /guard\.tryEnter\(\)/);
    assert.equal((detail.match(/decision\.mutate\(/g) ?? []).length, 1);
    assert.match(detail, /isCurrentQueryClient\(queryClient\)/);
  });

  it("the Confirm and Decline buttons exist only for an actionable proposal", () => {
    const detail = read(HERE, "proposal-detail-screen.tsx");

    assert.match(detail, /\{actionable \? \(/);
    assert.match(detail, /isProposalActionable\(proposal\.status\)/);
  });

  it("no financial arithmetic or number parsing in the Inbox code", () => {
    for (const name of [...screens, "inbox-data.ts", "inbox-proposal-actions.ts", "inbox-alerts.ts", "use-inbox-data.ts"]) {
      const code = read(HERE, name).replace(/\/\/.*$/gm, "");

      assert.doesNotMatch(code, /parseFloat|Number\(|parseInt|\.toFixed|Math\.(round|floor|ceil)|\bBigInt\b/, name);
    }
  });

  it("amounts are rendered as the backend strings (planned / applied / capacity)", () => {
    const detail = read(HERE, "proposal-detail-screen.tsx");

    for (const field of ["planned_amount", "applied_amount", "planned_total", "confirm_capacity", "source_amount"]) {
      assert.match(detail, new RegExp(`\\.${field}`), field);
    }
  });

  it("alerts: reviewed and resolved are shown separately, with a neutral name for a deleted subject", () => {
    const alerts = read(HERE, "alerts-screen.tsx");

    assert.match(alerts, /Resolved \{formatTime\(alert\.resolved_at\)\}/);
    assert.match(alerts, /Reviewed \{formatTime\(alert\.acknowledged_at\)\}/);
    assert.match(alerts, /acknowledged: reviewed/);
  });
});
