// VF-GOALS-PLANNING-002C1: mirrors the backend future-obligations contract
// (services/api/app/modules/future_obligations). A future obligation is a bill the
// user expects to owe and entered by hand: a forecast input, never a transaction.
// Amounts are the backend's decimal strings, never parsed, added or compared as
// numbers on the device.
export type ObligationSchedule = "one_time" | "monthly";
export type ObligationStatus = "active" | "archived";

export type FutureObligation = {
  id: string;
  user_id: string;
  name: string;
  description: string | null;
  schedule: ObligationSchedule;
  amount: string;
  currency: string;
  first_due_date: string;
  final_due_date: string | null;
  status: ObligationStatus;
  // The first due date on or after the server date; null when archived or none left.
  next_due_date: string | null;
  client_request_id: string | null;
  created_at: string;
  updated_at: string;
};

// The create request. currency is omitted to use the user's base currency;
// final_due_date is only for a monthly obligation.
export type FutureObligationCreateInput = {
  name: string;
  description?: string;
  schedule: ObligationSchedule;
  amount: string;
  currency?: string;
  first_due_date: string;
  final_due_date?: string;
  client_request_id?: string;
};

// A partial update: only changed fields are sent. description and
// final_due_date accept an explicit null to clear them.
export type FutureObligationUpdateInput = {
  name?: string;
  description?: string | null;
  amount?: string;
  currency?: string;
  first_due_date?: string;
  final_due_date?: string | null;
  status?: ObligationStatus;
};

export type UpcomingOccurrence = {
  obligation_id: string;
  name: string;
  schedule: ObligationSchedule;
  due_date: string;
  amount: string;
  currency: string;
};

export type CurrencyTotal = {
  currency: string;
  total: string;
  occurrence_count: number;
};

export type UpcomingMonth = {
  period_start: string;
  period_end: string;
  occurrence_count: number;
  base_currency_total: string;
  totals_by_currency: CurrencyTotal[];
  occurrences: UpcomingOccurrence[];
};

export type UpcomingObligations = {
  as_of: string;
  base_currency: string;
  horizon_months: number;
  window_start: string;
  window_end: string;
  is_base_total_complete: boolean;
  excluded_currencies: string[];
  base_currency_window_total: string;
  totals_by_currency: CurrencyTotal[];
  months: UpcomingMonth[];
};
