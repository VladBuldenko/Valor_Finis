import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { ApiError, httpApiError } from "./api-error.ts";
import { describeCreateFailure } from "./create-failure.ts";

describe("create failure wording", () => {
  it("never claims a lost response means the record was not saved", () => {
    const outcomes = [
      new ApiError({ kind: "network", message: "Network request failed" }),
      new ApiError({ kind: "timeout", message: "Request timed out." }),
      new ApiError({ kind: "malformed_response", message: "bad body" }),
      new ApiError({ kind: "cancelled", message: "aborted" }),
      httpApiError("http", 502, "<html>bad gateway</html>"),
      httpApiError("http", 503, ""),
      httpApiError("http", 504, ""),
    ];

    for (const error of outcomes) {
      const failure = describeCreateFailure(error, "income", "Unable to create income.");

      assert.equal(failure.outcomeUnknown, true);
      assert.equal(failure.discardAttempt, false);
      assert.match(failure.message, /could not confirm/i);
      assert.doesNotMatch(failure.message, /not saved|was not|wasn't|failed to save|did not save/i);
      assert.doesNotMatch(failure.title, /failed/i);
    }
  });

  it("keeps the app's own coded 503 (nothing was written) as a definite failure with its message", () => {
    const failure = describeCreateFailure(
      new ApiError({
        kind: "http",
        message: "API request failed: 503",
        status: 503,
        code: "fx_provider_unavailable",
        detail: "Currency conversion is temporarily unavailable. Please try again shortly.",
      }),
      "expense",
      "Unable to create expense.",
    );

    assert.equal(failure.outcomeUnknown, false);
    assert.equal(failure.title, "Create expense failed");
  });

  it("treats a definite rejection as a failure and keeps the backend's domain message", () => {
    const failure = describeCreateFailure(
      httpApiError("http", 409, '{"detail":"Archived account cannot receive new transactions."}'),
      "expense",
      "Unable to create expense.",
    );

    assert.equal(failure.outcomeUnknown, false);
    assert.equal(failure.title, "Create expense failed");
    assert.equal(failure.message, "Archived account cannot receive new transactions.");
  });

  it("drops the key only when the backend says it belongs to a different request", () => {
    const conflict = new ApiError({
      kind: "http",
      message: 'API request failed: 409 {"code":"income_idempotency_conflict"}',
      status: 409,
      code: "income_idempotency_conflict",
    });
    const otherConflict = new ApiError({ kind: "http", message: "x", status: 409, code: "expense_idempotency_conflict" });

    assert.equal(describeCreateFailure(conflict, "income", "x").discardAttempt, true);
    assert.equal(describeCreateFailure(otherConflict, "income", "x").discardAttempt, false);
    assert.doesNotMatch(describeCreateFailure(conflict, "income", "x").message, /client_request_id|uuid/i);
  });

  it("falls back to the caller's text when the failure carries no usable message", () => {
    const failure = describeCreateFailure(undefined, "income", "Unable to create income.");

    assert.equal(failure.message, "Unable to create income.");
    assert.equal(failure.outcomeUnknown, false);
  });
});
