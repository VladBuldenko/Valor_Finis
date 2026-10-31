// MF2-SR04: what users can read after a failed request.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { getGoalErrorMessage } from "../features/goals/goal-error-message.ts";
import { ApiError, httpApiError } from "./api-error.ts";
import { getApiErrorMessage, readApiFailure } from "./api-error-message.ts";
import {
  AUTH_UNAVAILABLE_MESSAGE,
  CANCELLED_MESSAGE,
  FORBIDDEN_MESSAGE,
  NETWORK_ERROR_MESSAGE,
  SERVER_ERROR_MESSAGE,
  SIGN_IN_AGAIN_MESSAGE,
  TIMEOUT_MESSAGE,
  UNAVAILABLE_MESSAGE,
  UNREADABLE_MESSAGE,
  getAuthErrorMessage,
  getUserFacingErrorMessage,
} from "./user-facing-error.ts";
import { makeHarness } from "./api-test-support.ts";

const FALLBACK = "Unable to save.";
const SECRET = "internal-host.corp.example";
const SENSITIVE = [SECRET, "Traceback", "psycopg2", "<html", "SELECT", "api.test", "token-1", "/api/v1"];

// Both shapes a screen can receive for the same HTTP failure.
function both(status: number, body: string): [string, unknown][] {
  return [
    ["typed ApiError", httpApiError(status === 401 ? "unauthorized" : "http", status, body)],
    ["legacy wrapped Error", new Error(`API request failed: ${status} ${body}`)],
  ];
}

function assertClean(text: string): void {
  for (const needle of SENSITIVE) {
    assert.ok(!text.includes(needle), `"${needle}" leaked into "${text}"`);
  }
}

describe("5xx bodies are never shown", () => {
  const cases: [string, number, string][] = [
    ["HTTP 500 with an HTML page", 500, `<html><body>Internal Server Error at ${SECRET}</body></html>`],
    ["HTTP 500 with JSON diagnostics", 500, JSON.stringify({ detail: `psycopg2.OperationalError: connection to ${SECRET} refused`, trace: "Traceback (most recent call last)" })],
    ["HTTP 500 with a plain string detail", 500, JSON.stringify({ detail: `Unhandled error on ${SECRET}` })],
    ["HTTP 500 with a malformed body", 500, `{"detail": "Traceback ${SECRET}`],
    ["HTTP 500 with an empty body", 500, ""],
    ["HTTP 501", 501, JSON.stringify({ detail: `not implemented ${SECRET}` })],
  ];

  for (const [name, status, body] of cases) {
    for (const [shape, error] of both(status, body)) {
      it(`${name} (${shape}) shows only the neutral message`, () => {
        const text = getUserFacingErrorMessage(error, FALLBACK);

        assert.equal(text, SERVER_ERROR_MESSAGE);
        assertClean(text);
      });
    }
  }

  for (const status of [502, 503, 504]) {
    for (const [shape, error] of both(status, `<html>${SECRET} gateway</html>`)) {
      it(`HTTP ${status} (${shape}) shows the "temporarily unavailable" message`, () => {
        const text = getUserFacingErrorMessage(error, FALLBACK);

        assert.equal(text, UNAVAILABLE_MESSAGE);
        assertClean(text);
      });
    }
  }
});

describe("expected 4xx domain messages are preserved", () => {
  for (const [shape, error] of both(409, JSON.stringify({ detail: "Archived account cannot receive new transactions." }))) {
    it(`HTTP 409 domain message (${shape})`, () => {
      assert.equal(getUserFacingErrorMessage(error, FALLBACK), "Archived account cannot receive new transactions.");
    });
  }

  for (const [shape, error] of both(422, JSON.stringify({ detail: [{ msg: "Input should be greater than 0", loc: ["body", "amount"] }] }))) {
    it(`HTTP 422 validation message (${shape})`, () => {
      assert.equal(getUserFacingErrorMessage(error, FALLBACK), "Input should be greater than 0");
    });
  }

  for (const [shape, error] of both(404, JSON.stringify({ detail: "Goal not found." }))) {
    it(`HTTP 404 message (${shape})`, () => {
      assert.equal(getUserFacingErrorMessage(error, FALLBACK), "Goal not found.");
    });
  }

  for (const [shape, error] of both(400, "<html>Bad Request</html>")) {
    it(`a 4xx without a usable message falls back, never the body (${shape})`, () => {
      assert.equal(getUserFacingErrorMessage(error, FALLBACK), FALLBACK);
    });
  }

  for (const [shape, error] of both(409, JSON.stringify({ detail: `Traceback (most recent call last): boom at ${SECRET}` }))) {
    it(`a technical-looking 4xx detail is not shown (${shape})`, () => {
      assert.equal(getUserFacingErrorMessage(error, FALLBACK), FALLBACK);
    });
  }

  it("an over-long 4xx detail is not shown", () => {
    const [, error] = both(422, JSON.stringify({ detail: "x".repeat(400) }))[0];

    assert.equal(getUserFacingErrorMessage(error, FALLBACK), FALLBACK);
  });

  it("401 and 403 get fixed texts", () => {
    assert.equal(getUserFacingErrorMessage(httpApiError("unauthorized", 401, "{}"), FALLBACK), SIGN_IN_AGAIN_MESSAGE);
    assert.equal(getUserFacingErrorMessage(httpApiError("http", 403, '{"detail":"nope"}'), FALLBACK), FORBIDDEN_MESSAGE);
  });
});

describe("non-HTTP failures", () => {
  it("a network failure with a sensitive diagnostic string shows only the fixed text", async () => {
    const h = makeHarness({
      respond: async () => {
        throw new TypeError(`Failed to fetch https://${SECRET}/api/v1/secret?token=token-1`);
      },
    });
    const failure = await h.transport.request("/api/v1/secret", { method: "POST" }).then(
      () => null,
      (error: unknown) => error,
    );

    assert.ok(failure instanceof ApiError);
    assert.equal(failure.kind, "network");

    const text = getUserFacingErrorMessage(failure, FALLBACK);

    assert.equal(text, NETWORK_ERROR_MESSAGE);
    assertClean(text);
  });

  it("each kind maps to a fixed text", () => {
    const kinds = {
      timeout: TIMEOUT_MESSAGE,
      cancelled: CANCELLED_MESSAGE,
      network: NETWORK_ERROR_MESSAGE,
      malformed_response: UNREADABLE_MESSAGE,
      unauthenticated: SIGN_IN_AGAIN_MESSAGE,
    } as const;

    for (const [kind, expected] of Object.entries(kinds)) {
      const error = new ApiError({ kind: kind as keyof typeof kinds, message: `raw ${SECRET}` });

      assert.equal(getUserFacingErrorMessage(error, FALLBACK), expected);
    }
  });

  it("an unrecognised Error or value gives the fallback, never error.message", () => {
    assert.equal(getUserFacingErrorMessage(new Error(`boom at ${SECRET}`), FALLBACK), FALLBACK);
    assert.equal(getUserFacingErrorMessage(new TypeError("Network request failed"), FALLBACK), FALLBACK);

    for (const value of ["text", null, undefined, 42, { message: SECRET }]) {
      assert.equal(getUserFacingErrorMessage(value, FALLBACK), FALLBACK);
    }
  });
});

describe("authentication errors", () => {
  function authError(name: string, message: string): Error {
    const error = new Error(message);

    error.name = name;

    return error;
  }

  it("shows the auth service's own message for a rejected sign-in", () => {
    assert.equal(getAuthErrorMessage(authError("AuthApiError", "Invalid login credentials"), "Unable to sign in."), "Invalid login credentials");
  });

  it("shows a fixed text for connectivity errors and the fallback for everything else", () => {
    assert.equal(getAuthErrorMessage(authError("AuthRetryableFetchError", `Failed to fetch ${SECRET}`), "x"), AUTH_UNAVAILABLE_MESSAGE);
    assert.equal(getAuthErrorMessage(authError("AuthUnknownError", `weird ${SECRET}`), "Unable to sign in."), "Unable to sign in.");
    assert.equal(getAuthErrorMessage(new Error(`boom ${SECRET}`), "Unable to sign out."), "Unable to sign out.");
    assert.equal(getAuthErrorMessage("text", "Unable to sign out."), "Unable to sign out.");
  });
});

describe("compatibility of the existing mappers", () => {
  it("getApiErrorMessage still returns 4xx details and validation messages for both shapes", () => {
    for (const [, error] of both(409, JSON.stringify({ detail: "Duplicate name." }))) {
      assert.equal(getApiErrorMessage(error, FALLBACK), "Duplicate name.");
    }

    for (const [, error] of both(422, JSON.stringify({ detail: [{ msg: "Field required" }] }))) {
      assert.equal(getApiErrorMessage(error, FALLBACK), "Field required");
    }
  });

  it("getApiErrorMessage never returns a 5xx detail or body", () => {
    for (const [, error] of both(500, JSON.stringify({ detail: `internal ${SECRET}` }))) {
      assert.equal(getApiErrorMessage(error, FALLBACK), FALLBACK);
    }

    for (const [, error] of both(503, JSON.stringify({ detail: [{ msg: `down ${SECRET}` }] }))) {
      assert.equal(getApiErrorMessage(error, FALLBACK), FALLBACK);
    }
  });

  it("getApiErrorMessage still passes a non-API Error message through (existing contract)", () => {
    assert.equal(getApiErrorMessage(new TypeError("Network request failed"), FALLBACK), "Network request failed");
  });

  it("readApiFailure keeps status and string detail for application logic, even for 5xx", () => {
    for (const [, error] of both(500, JSON.stringify({ detail: "kept for logic" }))) {
      assert.deepEqual(readApiFailure(error), { status: 500, detail: "kept for logic" });
    }
  });

  it("ApiError keeps status, detail, kind and code available", () => {
    const error = httpApiError("http", 500, JSON.stringify({ detail: "d", code: "internal_error" }));

    assert.deepEqual(
      { kind: error.kind, status: error.status, detail: error.detail, code: error.code },
      { kind: "http", status: 500, detail: "d", code: "internal_error" },
    );
    assert.equal(error.message, `API request failed: 500 ${error.body}`, "message unchanged for the parsing helpers");
  });

  it("getGoalErrorMessage hides 5xx bodies and non-JSON 4xx bodies, keeps 4xx details", () => {
    for (const [, error] of both(500, JSON.stringify({ detail: `internal ${SECRET}` }))) {
      assert.equal(getGoalErrorMessage(error, FALLBACK), FALLBACK);
    }

    for (const [, error] of both(400, "<html>bad</html>")) {
      assert.equal(getGoalErrorMessage(error, FALLBACK), FALLBACK);
    }

    for (const [, error] of both(409, JSON.stringify({ detail: "Goal is archived." }))) {
      assert.equal(getGoalErrorMessage(error, FALLBACK), "Goal is archived.");
    }
  });
});
