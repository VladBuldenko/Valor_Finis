// The AUTO enable gate (VF-020F5). Pure and Node-testable.
//
// Turning an AUTO rule on needs a PROOF that the user was shown a successful
// backend preview of this exact rule version and sample. The proof is
// transient client state only: nothing is stored on the server, nothing in
// AsyncStorage, and the backend has no expected-version token, so this is an
// advisory snapshot, not an atomic guarantee.
//
// Where the facts live: the preview itself is cached by TanStack Query under a
// key that contains user + rule id + rule version + sample, so a different
// rule version or sample is a different entry. A "viewed" record is kept per
// QueryClient (one per signed-in user; a new one replaces it on sign-out or
// user change, which drops every record with it). A record is honoured only
// while ALL of these still hold:
//   - the cached preview exists, is not invalidated and was not replaced;
//   - the Goal and Account cache families have not been invalidated or
//     refetched since it was viewed (their figures are inside the preview);
//   - the proof was issued by this store for the same user, rule and version.
import type { QueryClient } from "@tanstack/react-query";

import { accountKeys, financialRuleKeys, goalKeys } from "./financial-rule-query-keys.ts";
import type { FinancialRule, IncomeSource, RulePreview } from "./financial-rule.types.ts";

export type PreviewInputs = {
  // Exactly the text sent to the backend (decimal string).
  amount: string;
  source: IncomeSource | null;
};

type Subject = { userId: string; ruleId: string; ruleVersion: number; inputs: PreviewInputs };

export function previewKeyFor(subject: Subject) {
  return financialRuleKeys.preview(subject.userId, {
    ruleId: subject.ruleId,
    ruleVersion: subject.ruleVersion,
    sampleAmount: subject.inputs.amount,
    sampleSource: subject.inputs.source,
  });
}

export const sameInputs = (a: PreviewInputs, b: PreviewInputs): boolean =>
  a.amount === b.amount && a.source === b.source;

// Opaque to callers: only this module can issue one (checked through the
// `issued` set, so a hand-built object with the same fields is rejected).
export type PreviewProof = Readonly<{
  readonly userId: string;
  readonly ruleId: string;
  readonly ruleVersion: number;
  readonly inputs: PreviewInputs;
  readonly kind: "preview-proof";
}>;

const issued = new WeakSet<object>();

type ViewedRecord = { stamp: string; dataUpdatedAt: number };

// A fingerprint of the Goal and Account caches. It changes when either family
// is invalidated, refetched or gains/loses an entry, i.e. when the figures a
// preview was computed from may have moved.
function relatedStamp(queryClient: QueryClient, userId: string): string {
  const parts: string[] = [];

  for (const family of [goalKeys.family(userId), accountKeys.family(userId)]) {
    for (const query of queryClient.getQueryCache().findAll({ queryKey: [...family] })) {
      parts.push(`${query.queryHash}|${query.state.dataUpdatedAt}|${query.state.isInvalidated ? 1 : 0}`);
    }
  }

  return parts.sort().join(";");
}

export type PreviewAuthorizations = {
  // Call only once the successful result is on screen. False when the cached
  // preview is missing, invalid or not for this rule version.
  markViewed(subject: Subject): boolean;
  // A proof for the CURRENT inputs, or null.
  proofFor(subject: Subject): PreviewProof | null;
  // True only for a proof issued here that is still valid for `rule`.
  verify(proof: PreviewProof | undefined, rule: Pick<FinancialRule, "id" | "version">): boolean;
  revokeRule(ruleId: string): void;
  clear(): void;
  // For useSyncExternalStore: a counter that changes whenever a record is added or removed.
  subscribe(listener: () => void): () => void;
  getVersion(): number;
};

function createStore(queryClient: QueryClient): PreviewAuthorizations {
  const records = new Map<string, ViewedRecord>();
  const listeners = new Set<() => void>();
  let version = 0;
  const changed = (): void => {
    version += 1;
    listeners.forEach((listener) => listener());
  };
  const hashOf = (subject: Subject): string => JSON.stringify(previewKeyFor(subject));

  function stillValid(subject: Subject, record: ViewedRecord): boolean {
    const state = queryClient.getQueryState<RulePreview>(previewKeyFor(subject));
    const data = state?.data;

    return (
      state !== undefined &&
      data !== undefined &&
      !state.isInvalidated &&
      state.dataUpdatedAt === record.dataUpdatedAt &&
      data.hypothetical === true &&
      data.rule_id === subject.ruleId &&
      data.rule_version === subject.ruleVersion &&
      relatedStamp(queryClient, subject.userId) === record.stamp
    );
  }

  return {
    markViewed(subject) {
      const state = queryClient.getQueryState<RulePreview>(previewKeyFor(subject));
      const data = state?.data;

      if (
        state === undefined ||
        data === undefined ||
        state.isInvalidated ||
        data.hypothetical !== true ||
        data.rule_id !== subject.ruleId ||
        data.rule_version !== subject.ruleVersion
      ) {
        return false;
      }

      records.set(hashOf(subject), {
        stamp: relatedStamp(queryClient, subject.userId),
        dataUpdatedAt: state.dataUpdatedAt,
      });
      changed();

      return true;
    },

    proofFor(subject) {
      const record = records.get(hashOf(subject));

      if (record === undefined || !stillValid(subject, record)) {
        return null;
      }

      const proof: PreviewProof = Object.freeze({
        kind: "preview-proof" as const,
        userId: subject.userId,
        ruleId: subject.ruleId,
        ruleVersion: subject.ruleVersion,
        inputs: { ...subject.inputs },
      });

      issued.add(proof);

      return proof;
    },

    verify(proof, rule) {
      if (proof === undefined || !issued.has(proof)) {
        return false;
      }

      if (proof.ruleId !== rule.id || proof.ruleVersion !== rule.version) {
        return false;
      }

      const subject: Subject = {
        userId: proof.userId,
        ruleId: proof.ruleId,
        ruleVersion: proof.ruleVersion,
        inputs: proof.inputs,
      };
      const record = records.get(hashOf(subject));

      return record !== undefined && stillValid(subject, record);
    },

    revokeRule(ruleId) {
      let removed = false;

      for (const key of [...records.keys()]) {
        if ((JSON.parse(key) as unknown[])[2] === ruleId) {
          records.delete(key);
          removed = true;
        }
      }

      if (removed) {
        changed();
      }
    },

    clear() {
      records.clear();
      changed();
    },

    subscribe(listener) {
      listeners.add(listener);

      return () => {
        listeners.delete(listener);
      };
    },

    getVersion: () => version,
  };
}

// One store per QueryClient. A new client (sign-out, another user) has none,
// and the old store becomes unreachable with the old client.
const stores = new WeakMap<QueryClient, PreviewAuthorizations>();

export function previewAuthorizations(queryClient: QueryClient): PreviewAuthorizations {
  let store = stores.get(queryClient);

  if (store === undefined) {
    store = createStore(queryClient);
    stores.set(queryClient, store);
  }

  return store;
}
