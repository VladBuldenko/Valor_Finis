// VF-020F6: structural checks on the history screen wiring (the React Native
// screen itself cannot be mounted by the Node runner; its logic lives in the
// tested modules) and the guarantees that history cannot change other features.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { extractJsxText, extractStringLiterals, findForbiddenCopy, stripComments } from "./financial-rule-forbidden-copy.ts";
import { deriveInboxIndicator, type IndicatorInput } from "./inbox-data.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const APP = join(HERE, "../../../app");
const read = (...parts: string[]) => readFileSync(join(...parts), "utf8");
const code = (file: string) => stripComments(read(HERE, file));

const screen = code("rule-history-screen.tsx");
const card = code("rule-history-card.tsx");
const hook = code("use-execution-history.ts");

describe("route and entry points", () => {
  it("the route is thin and registered before the dynamic rule route", () => {
    assert.match(read(APP, "(app)/rules/history.tsx"), /RuleHistoryScreen/);
    assert.ok(read(APP, "(app)/rules/history.tsx").split("\n").length < 6);

    const layout = read(APP, "(app)/_layout.tsx");

    assert.match(layout, /name="rules\/history"/);
    assert.match(layout, /title: "History"/);
  });

  it("is reachable from the Rules list, the Inbox and an allocation rule's detail", () => {
    assert.match(code("rules-screen.tsx"), /href="\/rules\/history"/);
    assert.match(code("inbox-screen.tsx"), /href="\/rules\/history"[\s\S]{0,200}See all activity/);

    const detail = code("rule-detail-screen.tsx");
    const at = detail.indexOf('pathname: "/rules/history"');

    assert.ok(at > 0);
    assert.match(detail.slice(Math.max(0, at - 160), at), /rule_type === "INCOME_ALLOCATION"/);
    assert.match(detail.slice(at, at + 80), /rule_id: rule\.id/);
  });
});

describe("read-only", () => {
  const files = { screen, card, hook };

  it("uses only the list endpoints and no mutation, evaluation or write path", () => {
    for (const [name, source] of Object.entries(files)) {
      const methods = new Set([...source.matchAll(/financialRulesService\.(\w+)/g)].map((m) => m[1]));

      for (const method of methods) {
        assert.ok(["listExecutions", "listRules"].includes(method), `${name} calls ${method}`);
      }

      assert.doesNotMatch(source, /useMutation|mutationFn|\.mutate\(|apiRequest|method:\s*"(POST|PATCH|DELETE)"/, name);
      assert.doesNotMatch(source, /\bevaluate\b|request\(\s*"(inbox_open|foreground|income_recorded)"|applyRuleInvalidation|invalidateQueries/, name);
    }
  });

  it("reads the evaluation status but never asks for an evaluation", () => {
    assert.match(screen, /const \{ status: checkStatus \} = useRulesEvaluation\(\)/);
    assert.doesNotMatch(screen, /useRulesEvaluation\(\)\.request|\brequest\b/);
  });

  it("the next page is fetched only from a press, never from an effect or scroll", () => {
    assert.doesNotMatch(screen + card + hook, /useEffect|onEndReached|onScroll|useLayoutEffect/);

    const uses = [...screen.matchAll(/fetchNextPage\(\)/g)];

    assert.equal(uses.length, 2, "Load more and the next-page Retry");

    for (const use of uses) {
      assert.match(screen.slice(Math.max(0, use.index - 40), use.index), /onPress=\{\(\) => void feed\.$/);
    }
  });

  it("does not read the Inbox data and never imports other features' write services", () => {
    assert.doesNotMatch(screen + hook, /use-inbox-data|inbox-data|rule-preview|auto-activation|financial-rule-actions/);
  });

  it("the query hook forwards the abort signal and is disabled while signed out", () => {
    assert.match(hook, /queryFn: \(\{ pageParam, signal \}\) => listExecutions\(historyRequestFilters\(filters, pageParam\), signal\)/);
    assert.match(hook, /enabled: userId !== null/);
    assert.match(hook, /initialPageParam: 0/);
  });
});

describe("accessibility wiring", () => {
  it("cards are expandable buttons with an expanded state and a spoken summary", () => {
    assert.match(card, /accessibilityRole="button"[\s\S]{0,200}accessibilityLabel=\{view\.summaryLabel\}/);
    assert.match(card, /accessibilityState=\{\{ expanded \}\}/);
    assert.match(card, /accessibilityHint=\{expanded \?/);
  });

  it("filters are radios with a checked state and a text label; the picker is labelled", () => {
    assert.match(screen, /accessibilityRole="radio"[\s\S]{0,120}accessibilityState=\{\{ checked: selected \}\}[\s\S]{0,80}accessibilityLabel=\{label\}/);
    assert.match(screen, /<OptionPicker[\s\S]{0,120}title=\{HISTORY_COPY\.ruleFilterTitle\}/);
  });

  it("Load more names its progress; errors are alerts; loading states have labels", () => {
    assert.match(screen, /accessibilityLabel=\{`Load more, showing \$\{merged\.items\.length\} of \$\{merged\.total\}`\}/);
    assert.ok((screen.match(/accessibilityRole="alert"/g) ?? []).length >= 3);
    assert.match(screen, /accessibilityLabel=\{HISTORY_COPY\.loading\}/);
    assert.match(screen, /accessibilityLabel="Loading more history"/);
  });

  it("names are labelled as current names, in text and for screen readers", () => {
    assert.match(card, /\{view\.rule\} \(current name\)/);
    assert.match(card, /\{goal\.name\} \(current name\)/);
    assert.match(card, /\(current name\)\. Planned/);
  });

  it("a refresh gesture exists and does not run while a next page is loading", () => {
    assert.match(screen, /refreshing=\{feed\.isRefetching && !feed\.isFetchingNextPage\}/);
  });
});

describe("wording of the screen files", () => {
  it("breaks no copy rule and invents no retry, recovery or dead-event text", () => {
    const invented = /\b(dead|recover\w*|failed execution|retried|will be tried again|in the background|guarantee\w*)\b/i;
    const texts = [...extractStringLiterals(read(HERE, "rule-history-screen.tsx")), ...extractJsxText(read(HERE, "rule-history-screen.tsx")),
      ...extractStringLiterals(read(HERE, "rule-history-card.tsx")), ...extractJsxText(read(HERE, "rule-history-card.tsx"))];

    for (const text of texts) {
      assert.deepEqual(findForbiddenCopy(text), [], text);
      assert.doesNotMatch(text, invented, text);
    }
  });

  it("states the reservation is internal accounting, in the card footer", () => {
    assert.match(card, /COPY\.reservationMeaning/);
  });
});

describe("other features are untouched by history", () => {
  const input = (over: Partial<IndicatorInput> = {}): IndicatorInput => ({
    proposals: { status: "success", items: [], complete: true, available: true },
    alerts: { status: "success", items: [], complete: true, available: true },
    evaluation: "succeeded",
    now: 1_000,
    ...over,
  });

  it("the Inbox indicator has no execution input: history rows cannot make it 'attention'", () => {
    const withHistory = { ...input(), executions: [{ status: "awaiting_confirmation" }, { status: "blocked" }] } as unknown as IndicatorInput;

    assert.equal(deriveInboxIndicator(withHistory), "clear");
    assert.equal(deriveInboxIndicator(input()), "clear");
    assert.equal(deriveInboxIndicator(input({ proposals: { status: "loading", items: [], complete: false, available: true } })), "unknown");
  });

  it("the Inbox keeps its own bounded executions query and does not import the history", () => {
    const inbox = code("use-inbox-data.ts") + code("inbox-data.ts");

    assert.match(inbox, /inboxExecutions\(userId\)/);
    assert.match(inbox, /limit: RECENT_EXECUTIONS_LIMIT/);
    assert.doesNotMatch(inbox, /execution-history|executionHistory|use-execution-history/);
  });

  it("the evaluation provider and trigger know nothing about history", () => {
    assert.doesNotMatch(code("rules-evaluation-provider.ts") + code("financial-rule-evaluation-trigger.ts") + code("rules-evaluation-host.tsx"), /history|execution-history/i);
  });
});
