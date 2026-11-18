// VF-GOALS-PLANNING-002C1: form validation and request building for a future
// obligation. Pure and Node-testable. Everything is string based: amounts are
// never parsed into a JavaScript Number, and dates are compared as ISO strings
// (which sort like dates). The backend stays the authority; this only catches
// mistakes before a request is sent.
import type {
  FutureObligation,
  FutureObligationCreateInput,
  FutureObligationUpdateInput,
  ObligationSchedule,
} from "./future-obligation.types.ts";

export type FutureObligationFormValues = {
  name: string;
  schedule: ObligationSchedule;
  amount: string;
  // Blank on create means "use my base currency".
  currency: string;
  firstDueDate: string;
  // Only used for a monthly obligation.
  finalDueDate: string;
  description: string;
};

export const MAX_NAME_LENGTH = 100;
export const MAX_DESCRIPTION_LENGTH = 500;
// The backend's accepted range of a due date.
export const MIN_DUE_DATE = "2000-01-01";
export const MAX_DUE_DATE = "2100-12-31";

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

// Trims and converts a comma decimal separator to a point (the convention of
// this app's amount fields). Callers validate before treating it as safe to send.
export function normalizeObligationAmount(rawValue: string): string {
  return rawValue.trim().replace(",", ".");
}

function isLeapYear(year: number): boolean {
  return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
}

// True when `value` is a real calendar date in YYYY-MM-DD form (so 2026-02-30 and
// 2027-02-29 are not). Calendar arithmetic only; no time zones.
export function isRealIsoDate(value: string): boolean {
  if (!ISO_DATE.test(value)) {
    return false;
  }

  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(5, 7));
  const day = Number(value.slice(8, 10));

  if (month < 1 || month > 12 || day < 1) {
    return false;
  }

  const daysInMonth = [31, isLeapYear(year) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];

  return day <= daysInMonth;
}

function dateError(value: string, label: string): string | null {
  if (!ISO_DATE.test(value)) {
    return `${label} must use YYYY-MM-DD format.`;
  }

  if (!isRealIsoDate(value)) {
    return `${label} is not a real calendar date.`;
  }

  if (value < MIN_DUE_DATE || value > MAX_DUE_DATE) {
    return `${label} must be between ${MIN_DUE_DATE} and ${MAX_DUE_DATE}.`;
  }

  return null;
}

// The positive-amount rule shared with the other money forms: digits with up to 2
// decimal places, not zero, and no more than the backend's 10 integer digits.
function amountError(rawValue: string): string | null {
  const normalized = normalizeObligationAmount(rawValue);

  if (!normalized) {
    return "Amount is required.";
  }

  if (!/^\d+(\.\d{1,2})?$/.test(normalized)) {
    return "Amount must be a positive number with up to 2 decimal places.";
  }

  if (/^0+(\.0+)?$/.test(normalized)) {
    return "Amount must be greater than zero.";
  }

  if (normalized.split(".")[0].replace(/^0+(?=\d)/, "").length > 10) {
    return "Amount is too large.";
  }

  return null;
}

/**
 * Validates the form, first error wins; null when valid. The schedule decides
 * which fields count: a one-time bill has a single due date and no final date.
 */
export function validateFutureObligationForm(values: FutureObligationFormValues): string | null {
  const name = values.name.trim();

  if (!name) {
    return "Name is required.";
  }

  if (name.length > MAX_NAME_LENGTH) {
    return `Name must be ${MAX_NAME_LENGTH} characters or fewer.`;
  }

  const amount = amountError(values.amount);

  if (amount) {
    return amount;
  }

  const currency = values.currency.trim();

  if (currency && !/^[A-Za-z]{3}$/.test(currency)) {
    return "Currency must be exactly 3 letters, or left blank to use your base currency.";
  }

  const firstLabel = values.schedule === "one_time" ? "Due date" : "First due date";
  const first = dateError(values.firstDueDate.trim(), firstLabel);

  if (first) {
    return first;
  }

  const finalDueDate = values.finalDueDate.trim();

  if (values.schedule === "monthly" && finalDueDate) {
    const final = dateError(finalDueDate, "Final due date");

    if (final) {
      return final;
    }

    if (finalDueDate < values.firstDueDate.trim()) {
      return "Final due date cannot be before the first due date.";
    }
  }

  if (values.description.trim().length > MAX_DESCRIPTION_LENGTH) {
    return `Description must be ${MAX_DESCRIPTION_LENGTH} characters or fewer.`;
  }

  return null;
}

// The create payload (without the idempotency key): normalized, a blank currency,
// description or (monthly) final date omitted, a one-time bill never carrying a
// final date.
export function buildCreatePayload(
  values: FutureObligationFormValues,
): Omit<FutureObligationCreateInput, "client_request_id"> {
  const payload: Omit<FutureObligationCreateInput, "client_request_id"> = {
    name: values.name.trim(),
    schedule: values.schedule,
    amount: normalizeObligationAmount(values.amount),
    first_due_date: values.firstDueDate.trim(),
  };

  const currency = values.currency.trim().toUpperCase();

  if (currency) {
    payload.currency = currency;
  }

  const finalDueDate = values.finalDueDate.trim();

  if (values.schedule === "monthly" && finalDueDate) {
    payload.final_due_date = finalDueDate;
  }

  const description = values.description.trim();

  if (description) {
    payload.description = description;
  }

  return payload;
}

// The form values that describe an existing obligation (for the edit form).
export function valuesFromObligation(obligation: FutureObligation): FutureObligationFormValues {
  return {
    name: obligation.name,
    schedule: obligation.schedule,
    amount: obligation.amount,
    currency: obligation.currency,
    firstDueDate: obligation.first_due_date,
    finalDueDate: obligation.final_due_date ?? "",
    description: obligation.description ?? "",
  };
}

// The PATCH payload: only what the user changed, matching the backend's
// "omitted means unchanged". Clearing the description or the final date sends an
// explicit null. The schedule kind is never sent (it cannot change); a one-time
// bill never sends a final date.
export function buildUpdatePayload(
  original: FutureObligation,
  values: FutureObligationFormValues,
): FutureObligationUpdateInput {
  const changes: FutureObligationUpdateInput = {};
  const name = values.name.trim();
  const amount = normalizeObligationAmount(values.amount);
  const currency = values.currency.trim().toUpperCase();
  const firstDueDate = values.firstDueDate.trim();
  const description = values.description.trim() || null;

  if (name !== original.name) {
    changes.name = name;
  }

  if (amount !== original.amount) {
    changes.amount = amount;
  }

  if (currency && currency !== original.currency) {
    changes.currency = currency;
  }

  if (firstDueDate !== original.first_due_date) {
    changes.first_due_date = firstDueDate;
  }

  if (original.schedule === "monthly") {
    const finalDueDate = values.finalDueDate.trim() || null;

    if (finalDueDate !== original.final_due_date) {
      changes.final_due_date = finalDueDate;
    }
  }

  if (description !== original.description) {
    changes.description = description;
  }

  return changes;
}

// Today's date in the user's LOCAL calendar as YYYY-MM-DD (not toISOString(),
// which converts to UTC and can name the wrong day near midnight).
export function localIsoDate(now: Date): string {
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");

  return `${year}-${month}-${day}`;
}
