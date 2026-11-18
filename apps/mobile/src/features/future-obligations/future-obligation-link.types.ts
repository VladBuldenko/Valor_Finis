// VF-GOALS-PLANNING-002C2: mirrors the backend reconciliation contract
// (services/api/app/modules/future_obligations, api-contract.md 12B). A link says
// "this recorded expense corresponds to this bill date". It is relationship
// metadata the user chose: not a payment, and not a check with any bank. Amounts
// are the backend's decimal strings, never parsed, added or compared on the device.
import type { ObligationSchedule, ObligationStatus } from "./future-obligation.types.ts";

export type LinkedExpenseSummary = {
  link_id: string;
  expense_id: string;
  title: string;
  expense_date: string;
  amount: string;
  currency: string;
  linked_at: string;
};

// One scheduled due date of a bill. linked_expense is null when no expense is
// linked: that is not a statement that the bill is unpaid.
export type ReconciliationOccurrence = {
  obligation_id: string;
  name: string;
  schedule: ObligationSchedule;
  obligation_status: ObligationStatus;
  due_date: string;
  amount: string;
  currency: string;
  is_past: boolean;
  linked_expense: LinkedExpenseSummary | null;
};

export type ReconciliationOverview = {
  as_of: string;
  window_start: string;
  window_end: string;
  occurrences: ReconciliationOccurrence[];
};

export type CandidateExpense = {
  expense_id: string;
  title: string;
  expense_date: string;
  amount: string;
  currency: string;
};

// Counts of the user's other expenses that cannot be linked, by the first reason.
export type CandidateExclusions = {
  different_currency: number;
  different_amount: number;
  already_linked: number;
  dated_in_future: number;
};

export type OccurrenceCandidates = {
  obligation_id: string;
  due_date: string;
  amount: string;
  currency: string;
  candidate_limit: number;
  candidates: CandidateExpense[];
  excluded: CandidateExclusions;
};

export type OccurrenceLink = {
  id: string;
  obligation_id: string;
  due_date: string;
  expense_id: string;
  created_at: string;
};

export type OccurrenceLinkInput = {
  due_date: string;
  expense_id: string;
};
