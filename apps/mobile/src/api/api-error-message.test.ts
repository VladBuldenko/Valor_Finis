import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { getApiErrorMessage, readApiFailure } from "./api-error-message.ts";

const FALLBACK = "Something went wrong.";

// apiRequest (api-client.ts) throws this exact shape for a non-2xx response.
function apiFailure(status: number, body: string): Error {
  return new Error(`API request failed: ${status} ${body}`);
}

describe("getApiErrorMessage", () => {
  it("returns a FastAPI string detail as-is", () => {
    const error = apiFailure(409, JSON.stringify({ detail: "Archived account cannot receive new transactions." }));

    assert.equal(getApiErrorMessage(error, FALLBACK), "Archived account cannot receive new transactions.");
  });

  it("returns the first usable msg of a 422 validation array", () => {
    const body = JSON.stringify({
      detail: [
        { loc: ["body", "expense_date"], msg: "Input should be a valid date", type: "date_from_datetime_parsing" },
        { loc: ["body", "amount"], msg: "Input should be greater than 0", type: "greater_than" },
      ],
    });

    assert.equal(getApiErrorMessage(apiFailure(422, body), FALLBACK), "Input should be a valid date");
  });

  it("skips validation items that have no usable msg", () => {
    const body = JSON.stringify({
      detail: [null, "text", { msg: "" }, { msg: 7 }, {}, { msg: "Field required" }],
    });

    assert.equal(getApiErrorMessage(apiFailure(422, body), FALLBACK), "Field required");
  });

  it("falls back for a validation array without any usable msg", () => {
    assert.equal(getApiErrorMessage(apiFailure(422, JSON.stringify({ detail: [{}, null] })), FALLBACK), FALLBACK);
    assert.equal(getApiErrorMessage(apiFailure(422, JSON.stringify({ detail: [] })), FALLBACK), FALLBACK);
  });

  it("falls back for a body that is not valid JSON", () => {
    assert.equal(getApiErrorMessage(apiFailure(500, "<html>Bad Gateway</html>"), FALLBACK), FALLBACK);
    assert.equal(getApiErrorMessage(apiFailure(502, '{"detail": "cut off'), FALLBACK), FALLBACK);
  });

  it("falls back for an empty body", () => {
    assert.equal(getApiErrorMessage(apiFailure(500, ""), FALLBACK), FALLBACK);
  });

  it("falls back for an empty string detail", () => {
    assert.equal(getApiErrorMessage(apiFailure(400, JSON.stringify({ detail: "" })), FALLBACK), FALLBACK);
  });

  it("falls back for a detail that is neither a string nor an array", () => {
    for (const detail of [null, 42, true, { msg: "nested" }]) {
      assert.equal(getApiErrorMessage(apiFailure(400, JSON.stringify({ detail })), FALLBACK), FALLBACK);
    }
  });

  it("falls back for JSON bodies without a detail", () => {
    for (const body of ["{}", "null", "[]", '"text"', "123"]) {
      assert.equal(getApiErrorMessage(apiFailure(400, body), FALLBACK), FALLBACK);
    }
  });

  it("handles a multi-line body", () => {
    const body = JSON.stringify({ detail: "Line one." }, null, 2);

    assert.equal(getApiErrorMessage(apiFailure(400, body), FALLBACK), "Line one.");
  });

  it("keeps the message of a network error that is not an API failure", () => {
    assert.equal(getApiErrorMessage(new TypeError("Network request failed"), FALLBACK), "Network request failed");
    assert.equal(getApiErrorMessage(new Error("Failed to fetch"), FALLBACK), "Failed to fetch");
  });

  it("does not treat a message that merely mentions the wrapper as an API failure", () => {
    const error = new Error('retry later: API request failed: 500 {"detail":"x"}');

    assert.equal(getApiErrorMessage(error, FALLBACK), error.message);
  });

  it("returns the fallback for non-Error values", () => {
    for (const value of ["API request failed: 400 {}", { message: "boom" }, 42, null, undefined]) {
      assert.equal(getApiErrorMessage(value, FALLBACK), FALLBACK);
    }
  });
});

describe("readApiFailure", () => {
  it("returns the status and string detail of an API failure", () => {
    assert.deepEqual(readApiFailure(apiFailure(404, JSON.stringify({ detail: "Income not found." }))), {
      status: 404,
      detail: "Income not found.",
    });
  });

  it("returns a null detail for a 422 validation list", () => {
    assert.deepEqual(readApiFailure(apiFailure(422, JSON.stringify({ detail: [{ msg: "bad" }] }))), {
      status: 422,
      detail: null,
    });
  });

  it("keeps the status when the body is not JSON", () => {
    assert.deepEqual(readApiFailure(apiFailure(503, "Service Unavailable")), { status: 503, detail: null });
  });

  it("returns a null detail for an empty detail string", () => {
    assert.deepEqual(readApiFailure(apiFailure(400, JSON.stringify({ detail: "" }))), { status: 400, detail: null });
  });

  it("returns a null status for a network error", () => {
    assert.deepEqual(readApiFailure(new TypeError("Network request failed")), { status: null, detail: null });
  });

  it("returns a null status for non-Error values", () => {
    for (const value of ["API request failed: 400 {}", null, undefined, 1]) {
      assert.deepEqual(readApiFailure(value), { status: null, detail: null });
    }
  });
});
