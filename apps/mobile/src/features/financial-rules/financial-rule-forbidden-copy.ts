// Forbidden-copy rules for the Smart Rules screens (VF-020F1; decision record
// C1-C3, C7, C8 and gate BR-13). The patterns are tested against the string
// literals of this feature directory, and F2-F6 screens inherit the check by
// living there.
//
// This file is the only place in the directory allowed to contain the
// forbidden phrases (as patterns), so the scan skips it.
export type ForbiddenCopyRule = { id: string; rule: string; pattern: RegExp };

export const FORBIDDEN_COPY: readonly ForbiddenCopyRule[] = [
  // C3: no invented balances.
  { id: "aggregate-balance", rule: "C3", pattern: /\b(total|net|overall|combined)\s+(account\s+)?balance\b/i },
  { id: "safe-to-spend", rule: "C3", pattern: /\bsafe\s+to\s+spend\b/i },
  { id: "available-cash", rule: "C3", pattern: /\bavailable\s+cash\b|\bspendable\b/i },
  // C1: nothing implies execution while the app is closed (until Gate I).
  { id: "while-asleep", rule: "C1", pattern: /\bwhile\s+(you\s+)?(sleep|are\s+asleep|are\s+away|you'?re\s+away)\b/i },
  { id: "app-closed", rule: "C1", pattern: /\b(while|when|even\s+if|even\s+when)\s+(the\s+)?app\s+(is\s+)?(closed|off|not\s+open)\b/i },
  { id: "background", rule: "C1", pattern: /\bin\s+the\s+background\b|\bunattended\b/i },
  { id: "around-the-clock", rule: "C1", pattern: /\b24\s*\/\s*7\b|\baround\s+the\s+clock\b|\bovernight\b/i },
  { id: "always-watching", rule: "C1", pattern: /\b(always|constantly|continuously)\s+(watching|monitoring|checking|running)\b/i },
  // C2: a reservation is an earmark, never a transfer, deposit or payment.
  { id: "transfer-to-goal", rule: "C2", pattern: /\b(transfer\w*|deposit\w*|wire[sd]?|payment\w*)\b[^.]*\b(goal|reserv\w*)/i },
  { id: "goal-transfer", rule: "C2", pattern: /\b(goal|reserv\w*)\b[^.]*\b(transfer\w*|deposit\w*|wire[sd]?|payment\w*)\b/i },
  // C7: the Inbox entry has no count and never says "unread".
  { id: "unread", rule: "C7", pattern: /\bunread\b/i },
  // C8: a preview is never a promise.
  { id: "guarantee", rule: "C8", pattern: /\bguarantee\w*\b/i },
];

export type ForbiddenCopyHit = { id: string; rule: string; text: string };

export function findForbiddenCopy(text: string): ForbiddenCopyHit[] {
  return FORBIDDEN_COPY.filter((entry) => entry.pattern.test(text)).map((entry) => ({
    id: entry.id,
    rule: entry.rule,
    text,
  }));
}

// Removes // and /* */ comments so the scan sees code and string literals only.
// Quoted text is skipped over so "//" inside a string is kept.
export function stripComments(source: string): string {
  let out = "";
  let i = 0;

  while (i < source.length) {
    const ch = source[i];
    const next = source[i + 1];

    if (ch === '"' || ch === "'" || ch === "`") {
      let j = i + 1;

      while (j < source.length && source[j] !== ch) {
        j += source[j] === "\\" ? 2 : 1;
      }

      out += source.slice(i, j + 1);
      i = j + 1;
    } else if (ch === "/" && next === "/") {
      while (i < source.length && source[i] !== "\n") {
        i += 1;
      }
    } else if (ch === "/" && next === "*") {
      const end = source.indexOf("*/", i + 2);

      i = end === -1 ? source.length : end + 2;
    } else {
      out += ch;
      i += 1;
    }
  }

  return out;
}

// Every quoted or template string literal of a source file (comments removed).
export function extractStringLiterals(source: string): string[] {
  const code = stripComments(source);
  const literals: string[] = [];
  const pattern = /"((?:\\.|[^"\\\n])*)"|'((?:\\.|[^'\\\n])*)'|`((?:\\.|[^`\\])*)`/g;

  for (const match of code.matchAll(pattern)) {
    literals.push(match[1] ?? match[2] ?? match[3] ?? "");
  }

  return literals;
}
