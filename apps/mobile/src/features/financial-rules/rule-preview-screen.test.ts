// VF-020F5: the preview view model (verbatim backend figures, hypothetical
// copy, every outcome/effect) and structural checks on the screen wiring.
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { COPY } from "./financial-rule-copy.ts";
import { extractJsxText, extractStringLiterals, findForbiddenCopy } from "./financial-rule-forbidden-copy.ts";
import { PREVIEW_EFFECTS, PREVIEW_OUTCOMES } from "./financial-rule.types.ts";
import { buildPreviewView, turnOnBlockReason, type TurnOnFacts } from "./rule-preview-view.ts";
import { GOALS, preview } from "./preview-fixtures.test-support.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const APP = join(HERE, "../../../app");
const read = (...parts: string[]) => readFileSync(join(...parts), "utf8");
const names = (id: string) => (id === GOALS.first ? "Holiday" : null);

describe("view model: verbatim figures", () => {
  it("passes every backend decimal string through unchanged, in the server's order", () => {
    const view = buildPreviewView(preview(), "Save", names);

    assert.equal(view.heading, "If you received 3000.00 EUR");
    assert.deepEqual(view.rows.map((r) => [r.goal, r.planned, r.selected]), [
      ["Holiday", "300.00 EUR", "300.00 EUR"],
      ["Goal", "150.00 EUR", "0.00 EUR"],
    ]);
    assert.equal(view.planned, "450.00 EUR");
    assert.equal(view.selected, "300.00 EUR");
    assert.deepEqual(view.accountFigures.map((f) => f.value), [
      "1200.00 EUR", "3000.00 EUR", "4200.00 EUR", "500.00 EUR", "100.00 EUR", "3600.00 EUR",
    ]);
    assert.equal(view.serverDate, "2026-11-02");
    assert.equal(view.computedAt, "2026-11-02T09:30:00.123456+00:00");
    assert.match(view.ruleLine, /Save - Automatic - version 3/);
  });

  it("does not re-sort: a server order that is not by position or rank is kept", () => {
    const p = preview();
    const view = buildPreviewView({ ...p, items: [p.items[1], p.items[0]] }, "Save", names);

    assert.deepEqual(view.rows.map((r) => r.key), [p.items[1], p.items[0]].map((i) => `${i.position}-${i.goal_id}`));
  });

  it("figures that look inconsistent are shown as sent (the client never fixes them)", () => {
    const view = buildPreviewView(preview({ planned_total: "999.99", selected_total: "0.01" }), "Save", names);

    assert.equal(view.planned, "999.99 EUR");
    assert.equal(view.selected, "0.01 EUR");
  });
});

describe("view model: states and copy", () => {
  it("every outcome and every effect has a presentation, and every view says Example only", () => {
    for (const outcome of PREVIEW_OUTCOMES) {
      for (const effect of PREVIEW_EFFECTS) {
        const view = buildPreviewView(preview({ predicted_outcome: outcome, effect }), "Save", names);

        assert.equal(view.label, "Example only");
        assert.ok(view.outcome.label.length > 0);
        assert.ok(view.effect.length > 0);
        assert.ok(view.notices[0] === COPY.previewDisclaimer, "the hypothetical disclaimer always leads");
      }
    }
  });

  it("the four outcomes are told apart by text, not colour", () => {
    const labels = PREVIEW_OUTCOMES.map((o) => buildPreviewView(preview({ predicted_outcome: o }), "S", names).outcome.label);

    assert.equal(new Set(labels).size, 4);
  });

  it("would_apply and would_hold explain themselves differently; none says nothing is selected", () => {
    const apply = buildPreviewView(preview({ effect: "would_apply" }), "S", names).effect;
    const hold = buildPreviewView(preview({ effect: "would_hold" }), "S", names).effect;
    const none = buildPreviewView(preview({ effect: "none" }), "S", names).effect;

    assert.equal(apply, COPY.previewWouldApply);
    assert.equal(hold, COPY.previewWouldHold);
    assert.match(hold, /Nothing is reserved until you confirm/);
    assert.equal(none, COPY.previewNoAllocation);
  });

  it("reason codes are mapped (never shown raw) and unknown ones get the generic text", () => {
    assert.match(buildPreviewView(preview({ predicted_outcome: "blocked", reason_code: "insufficient_capacity" }), "S", names).reason ?? "", /./);
    assert.equal(buildPreviewView(preview({ reason_code: "brand_new_code" }), "S", names).reason, COPY.fallbackReason);
    assert.equal(buildPreviewView(preview({ reason_code: null }), "S", names).reason, null);
  });

  it("source_selected_by_rule false gets its own notice; true and null do not", () => {
    const sample = preview().sample_income;
    const notice = (flag: boolean | null) =>
      buildPreviewView(preview({ sample_income: { ...sample, source_selected_by_rule: flag } }), "S", names).sourceNotice;

    assert.equal(notice(false), COPY.previewSourceNotUsed);
    assert.equal(notice(true), null);
    assert.equal(notice(null), null);
  });

  it("the standing limitations are shown whenever the server sends them, unknown tokens never raw", () => {
    const view = buildPreviewView(preview({ notices: ["income_not_recorded", "other_enabled_rules_not_simulated", "real_event_eligibility_not_simulated", "mystery"] }), "S", names);

    assert.ok(view.notices.includes(COPY.previewIncomeNotRecorded));
    assert.ok(view.notices.includes(COPY.previewOtherRulesNotSimulated));
    assert.ok(view.notices.includes(COPY.previewEligibilityNotSimulated));
    assert.ok(!view.notices.some((n) => n.includes("mystery")));
  });
});

describe("the Turn on control's disabled reasons", () => {
  const ready: TurnOnFacts = {
    isAutoAllocation: true, statusOffersEnable: true, hasShownPreview: true,
    outOfDate: false, inputsMatchShown: true, hasValidProof: true, busy: false,
  };

  it("is enabled only when every fact holds", () => {
    assert.equal(turnOnBlockReason(ready), null);
  });

  it("each missing fact disables it with a readable reason", () => {
    const cases: Partial<TurnOnFacts>[] = [
      { isAutoAllocation: false }, { statusOffersEnable: false }, { hasShownPreview: false },
      { outOfDate: true }, { inputsMatchShown: false }, { hasValidProof: false }, { busy: true },
    ];

    for (const change of cases) {
      const reason = turnOnBlockReason({ ...ready, ...change });

      assert.ok(reason && reason.length > 5, JSON.stringify(change));
    }
  });
});

describe("screen wiring", () => {
  const screen = read(HERE, "rule-preview-screen.tsx");
  const detail = read(HERE, "rule-detail-screen.tsx");

  it("the route exists, is thin and is registered", () => {
    assert.match(read(APP, "(app)/rules/[id]/preview.tsx"), /RulePreviewScreen/);
    assert.ok(read(APP, "(app)/_layout.tsx").includes('name="rules/[id]/preview"'));
  });

  it("the enable POST is reachable only through the guarded runner", () => {
    const offenders: string[] = [];
    const walk = (dir: string) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const path = join(dir, entry.name);

        if (entry.isDirectory()) {
          walk(path);
        } else if (/\.(ts|tsx)$/.test(entry.name) && !entry.name.includes(".test")) {
          if (/\.enableRule\(|enableRule\s*\(/.test(readFileSync(path, "utf8")) && !/financial-rule-actions\.ts$|financial-rule\.api\.ts$/.test(path)) {
            offenders.push(path);
          }
        }
      }
    };

    walk(join(HERE, "../.."));
    walk(APP);
    assert.deepEqual(offenders, []);
  });

  it("the screen sends the enable through runner.run with the proof, behind a dialog, one at a time", () => {
    assert.match(screen, /runner\.run\(target, "enable", \{[\s\S]*?proof: activationProof/);
    assert.match(screen, /Alert\.alert\(AUTO_ACTIVATION_DIALOG\.title, autoActivationMessage/);
    assert.match(screen, /activationGuard\.tryEnter\(\)/);
    assert.match(screen, /previewGuard\.tryEnter\(\)/);
    assert.match(screen, /canTurnOn = turnOnReason === null/);
    assert.match(screen, /disabled=\{!canTurnOn\}/);
  });

  it("'viewed' is recorded from an effect after the result is displayed, never at fetch time", () => {
    assert.match(screen, /useEffect\(\(\) => \{[\s\S]*?markViewed\(/);
    assert.ok(!read(HERE, "rule-preview-flow.ts").includes("markViewed"));
    assert.match(screen, /!outOfDate \|\| !settled|outOfDate \|\| !settled/);
  });

  it("the session guard is applied to the preview and the activation", () => {
    assert.equal((screen.match(/isCurrentQueryClient\(queryClient\)/g) ?? []).length >= 3, true);
  });

  it("the detail screen sends an AUTO 'Turn on' to the example instead of enabling it", () => {
    assert.match(detail, /isAutoEnableBlocked\(rule\)[\s\S]{0,200}router\.push\(\{ pathname: "\/rules\/\[id\]\/preview"/);
    assert.match(detail, /pathname: "\/rules\/\[id\]\/preview"[\s\S]*?Example/);
  });

  it("sample inputs are kept: a failure never clears the amount or source", () => {
    assert.ok(!/setAmountText\(""\)|setSource\(null\)\s*;\s*\n\s*setMessage/.test(screen));
  });

  it("accessibility: roles, labels, live regions and non-colour status exist", () => {
    for (const piece of [
      'accessibilityLabel="Example income amount"',
      'accessibilityLabel="Show example"',
      'accessibilityLabel="Turn on automatic rule"',
      'accessibilityRole="radio"',
      'accessibilityLiveRegion="polite"',
      'accessibilityRole="alert"',
      "view.outcome.label",
      "view.label",
    ]) {
      assert.ok(screen.includes(piece), piece);
    }
  });
});

describe("no client arithmetic and approved copy", () => {
  const files = ["rule-preview-view.ts", "rule-preview-flow.ts", "rule-preview-screen.tsx", "auto-activation.ts"];

  it("no numeric conversion or arithmetic is applied to amounts", () => {
    for (const file of files) {
      const code = read(HERE, file).replace(/\/\/.*$/gm, "");

      assert.doesNotMatch(code, /parseFloat|parseInt|Number\(|toFixed|BigInt|Math\.|Decimal/, file);
      assert.doesNotMatch(code, /\b(planned|selected|amount|total|reservable|capacity|floor|holds?)\w*\s*[-*/]\s*\w/i, file);
    }
  });

  it("the new strings pass the forbidden-copy scan and avoid result-as-fact words", () => {
    for (const file of files) {
      const source = read(HERE, file);
      const texts = [...extractStringLiterals(source), ...extractJsxText(source)];

      for (const text of texts) {
        assert.deepEqual(findForbiddenCopy(text), [], `${file}: ${text}`);
        assert.doesNotMatch(text, /\b(done|completed|transaction)\b/i, `${file}: ${text}`);
      }
    }
  });

  it("the example is always labelled and never described as a promise", () => {
    assert.equal(COPY.previewLabel, "Example only");
    assert.match(COPY.previewDisclaimer, /Nothing was recorded or reserved/);
    assert.match(COPY.previewDisclaimer, /a real income may turn out differently/);
  });
});
