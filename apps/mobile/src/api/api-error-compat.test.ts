import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { getApiErrorMessage, readApiFailure } from "./api-error-message.ts";
import { ApiError, isApiError, isAuthApiError, httpApiError, parseErrorBody } from "./api-error.ts";
import { getGoalErrorMessage } from "../features/goals/goal-error-message.ts";

const FALLBACK = "Something went wrong.";

describe("ApiError is a drop-in replacement for the historical Error", () => {
  it("is an Error with the exact historical HTTP message", () => {
    const error = httpApiError("http", 409, '{"detail":"Archived."}');

    assert.ok(error instanceof Error);
    assert.ok(isApiError(error));
    assert.equal(error.name, "ApiError");
    assert.equal(error.message, 'API request failed: 409 {"detail":"Archived."}');
    assert.match(error.message, /^API request failed: 409 /);
  });

  it("works with getApiErrorMessage for string details and validation lists", () => {
    assert.equal(
      getApiErrorMessage(httpApiError("http", 409, '{"detail":"Archived."}'), FALLBACK),
      "Archived.",
    );
    assert.equal(
      getApiErrorMessage(httpApiError("http", 422, '{"detail":[{"msg":"Field required"}]}'), FALLBACK),
      "Field required",
    );
    assert.equal(getApiErrorMessage(httpApiError("http", 502, "<html>"), FALLBACK), FALLBACK);
  });

  it("works with readApiFailure", () => {
    assert.deepEqual(readApiFailure(httpApiError("http", 404, '{"detail":"Not found."}')), {
      status: 404,
      detail: "Not found.",
    });
    assert.deepEqual(readApiFailure(httpApiError("unauthorized", 401, "{}")), { status: 401, detail: null });
  });

  it("works with the goal error mapper that parses the message", () => {
    assert.equal(
      getGoalErrorMessage(httpApiError("http", 409, '{"detail":"Goal is archived."}'), FALLBACK),
      "Goal is archived.",
    );
  });

  it("keeps non-HTTP messages readable through the existing helpers", () => {
    const network = new ApiError({ kind: "network", message: "Network request failed" });
    const timeout = new ApiError({ kind: "timeout", message: "Request timed out." });

    assert.equal(getApiErrorMessage(network, FALLBACK), "Network request failed");
    assert.equal(getApiErrorMessage(timeout, FALLBACK), "Request timed out.");
    assert.deepEqual(readApiFailure(network), { status: null, detail: null });
  });

  it("keeps the old no-session message", () => {
    const error = new ApiError({ kind: "unauthenticated", message: "User is not authenticated." });

    assert.equal(error.message, "User is not authenticated.");
  });
});

describe("classification helpers", () => {
  it("isAuthApiError covers 401 and a missing session only", () => {
    assert.equal(isAuthApiError(httpApiError("unauthorized", 401, "{}")), true);
    assert.equal(isAuthApiError(new ApiError({ kind: "unauthenticated", message: "x" })), true);
    assert.equal(isAuthApiError(httpApiError("http", 403, "{}")), false);
    assert.equal(isAuthApiError(new Error("API request failed: 401 {}")), false);
    assert.equal(isAuthApiError(null), false);
  });

  it("parseErrorBody never throws", () => {
    for (const text of ["", "null", "[]", '"x"', "{", "123", '{"detail":{"a":1}}']) {
      assert.deepEqual(parseErrorBody(text), { detail: null, code: null });
    }
  });

  it("parseErrorBody reads detail and a valid code", () => {
    assert.deepEqual(parseErrorBody('{"detail":"d","code":"goal_archived"}'), {
      detail: "d",
      code: "goal_archived",
    });
  });
});
