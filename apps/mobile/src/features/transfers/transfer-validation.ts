import {
  normalizeAccountDecimalAmount,
  validateAccountDecimalAmount,
} from "../accounts/account-amount-validation";
import type { Account } from "../accounts/account.types";
import type { TransferCreatePayload } from "./transfer-create-attempts";

// Matches backend AccountTransferCreate.description max_length
// (services/api/app/modules/accounts/account_transfer_schemas.py).
const MAX_DESCRIPTION_LENGTH = 500;

// Backend amount is Decimal(max_digits=12, decimal_places=2), so at most 10
// digits before the decimal point (leading zeros do not count).
const MAX_WHOLE_DIGITS = 10;

const DATE_SHAPE = /^\d{4}-\d{2}-\d{2}$/;

export type TransferFormValues = {
  // Resolved from the ACTIVE Accounts currently offered by the pickers;
  // undefined when nothing (or no longer valid) is selected, so a hidden
  // or stale selection can never be submitted.
  sourceAccount: Account | undefined;
  destinationAccount: Account | undefined;
  amount: string;
  transferDate: string;
  description: string;
};

// Returns whether a value has the YYYY-MM-DD shape. Calendar validity
// (e.g. 2026-02-31) is left to the backend.
export function isTransferDateShape(value: string): boolean {
  return DATE_SHAPE.test(value);
}

// Converts an amount that already passed validateAccountDecimalAmount into
// its canonical string: no leading zeros, exactly two decimals
// ("0300" -> "300.00", "12.5" -> "12.50"). String operations only -- the
// value is never parsed into a JavaScript Number. Canonical form makes
// equal amounts identical strings, so a retry typed as "300" after a
// failed "300.00" still reuses the same idempotency key.
function toCanonicalAmount(normalizedAmount: string): string {
  const [wholePart, fractionPart = ""] = normalizedAmount.split(".");
  const whole = wholePart.replace(/^0+(?=\d)/, "");

  return `${whole}.${fractionPart.padEnd(2, "0")}`;
}

/**
 * Validates the create-transfer form and builds the exact normalized
 * payload to send. First-error-wins.
 *
 * Checks what the form can know: both Accounts selected and distinct,
 * same currency, amount shape/sign/precision, date shape, description
 * length. The backend stays authoritative for everything, including
 * calendar-date validity, ownership, archived status, and the currency
 * rule. There is deliberately no balance check -- a transfer may make the
 * source balance negative.
 *
 * Returns:
 * - { payload } when valid, with a canonical amount, trimmed date, and
 *   trimmed description (null when blank);
 * - { error } with a user-facing message otherwise.
 */
export function prepareTransferCreatePayload(
  values: TransferFormValues,
): { payload: TransferCreatePayload } | { error: string } {
  const { sourceAccount, destinationAccount } = values;

  if (!sourceAccount) {
    return { error: "Select a source account." };
  }

  if (!destinationAccount) {
    return { error: "Select a destination account." };
  }

  if (sourceAccount.id === destinationAccount.id) {
    return { error: "Source and destination accounts must be different." };
  }

  if (sourceAccount.currency !== destinationAccount.currency) {
    return {
      error: "Source and destination accounts must use the same currency.",
    };
  }

  const amountError = validateAccountDecimalAmount(values.amount, "Amount");

  if (amountError) {
    return { error: amountError };
  }

  const amount = toCanonicalAmount(normalizeAccountDecimalAmount(values.amount));

  if (amount.split(".")[0].length > MAX_WHOLE_DIGITS) {
    return {
      error: `Amount must have at most ${MAX_WHOLE_DIGITS} digits before the decimal point.`,
    };
  }

  const transferDate = values.transferDate.trim();

  if (!isTransferDateShape(transferDate)) {
    return { error: "Transfer date must use YYYY-MM-DD format." };
  }

  const description = values.description.trim();

  if (description.length > MAX_DESCRIPTION_LENGTH) {
    return {
      error: `Description must be ${MAX_DESCRIPTION_LENGTH} characters or fewer.`,
    };
  }

  return {
    payload: {
      source_account_id: sourceAccount.id,
      destination_account_id: destinationAccount.id,
      amount,
      transfer_date: transferDate,
      description: description || null,
    },
  };
}
