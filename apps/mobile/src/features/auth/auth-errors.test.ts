// MF-4: classifying Supabase Auth failures without reading their text. Pure.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { classifyAuthFailure, weakPasswordReasons } from "./auth-errors.ts";

const api = (code: string, status = 400) => ({ name: "AuthApiError", code, status, message: "SERVER TEXT: User already registered" });

describe("classifyAuthFailure", () => {
  it("maps the documented codes", () => {
    const table: [unknown, string][] = [
      [api("user_already_exists", 422), "user_exists"],
      [api("email_exists", 422), "user_exists"],
      [api("over_email_send_rate_limit", 429), "rate_limited"],
      [api("over_request_rate_limit", 429), "rate_limited"],
      [{ name: "AuthApiError", status: 429 }, "rate_limited"],
      [api("weak_password", 422), "weak_password"],
      [{ name: "AuthWeakPasswordError", reasons: ["length"] }, "weak_password"],
      [api("same_password", 422), "same_password"],
      [api("email_address_invalid"), "invalid_email"],
      [api("validation_failed"), "invalid_email"],
      [api("signup_disabled", 422), "signup_disabled"],
      [api("session_not_found", 403), "session_missing"],
      [api("refresh_token_already_used"), "session_missing"],
      [{ name: "AuthSessionMissingError" }, "session_missing"],
      [api("otp_expired", 403), "link_expired"],
      [api("flow_state_not_found", 404), "link_expired"],
      [{ name: "AuthRetryableFetchError", status: 0 }, "network"],
      [{ name: "AuthApiError", status: 503 }, "network"],
      [{ name: "AbortError" }, "network"],
      [{ name: "TypeError" }, "network"],
      [api("something_new"), "other"],
      [new Error("User already registered"), "other"],
      [null, "other"],
      ["User already registered", "other"],
      [undefined, "other"],
    ];

    for (const [error, expected] of table) {
      assert.equal(classifyAuthFailure(error), expected, JSON.stringify(error));
    }
  });

  it("never classifies by message text", () => {
    assert.equal(classifyAuthFailure({ name: "AuthApiError", message: "User already registered", status: 400 }), "other");
    assert.equal(classifyAuthFailure({ message: "rate limit exceeded" }), "other");
  });
});

describe("weakPasswordReasons", () => {
  it("returns fixed phrases only", () => {
    assert.deepEqual(weakPasswordReasons({ reasons: ["length", "characters", "pwned", "SERVER-TEXT"] }), [
      "make it longer",
      "mix letters, numbers and symbols",
      "avoid a password that appeared in a data leak",
    ]);
    assert.deepEqual(weakPasswordReasons({}), []);
    assert.deepEqual(weakPasswordReasons(null), []);
  });
});
