// MF-4: the auth-link parser. Pure.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { AUTH_CALLBACK_PATH, buildAuthRedirectUrl, isAppSpecificScheme, parseAuthLink, type ParseOptions } from "./auth-link.ts";

const OPTIONS: ParseOptions = { schemes: ["valorfinis"] };
const parse = (url: unknown, options = OPTIONS) => parseAuthLink(url, options);
const ACCESS = "eyJhbGciOiJIUzI1NiJ9.payload.signature";
const REFRESH = "refresh-token_value-1";
const base = "valorfinis://auth/callback";

describe("what is and is not an auth link", () => {
  it("accepts only the app's own scheme and the exact path", () => {
    assert.deepEqual(parse("mobile://auth/callback#access_token=a&refresh_token=b&type=recovery"), { kind: "ignore" });
    assert.deepEqual(parse("https://auth/callback?code=abc"), { kind: "ignore" });
    assert.deepEqual(parse("valorfinis://goals"), { kind: "ignore" });
    assert.deepEqual(parse("valorfinis://auth/callbackx?code=abc"), { kind: "ignore" });
    assert.deepEqual(parse("valorfinis://auth/callback/extra?code=abc"), { kind: "ignore" });
    assert.deepEqual(parse("valorfinis://evil.example/auth/callback?code=abc"), { kind: "ignore" });
    assert.deepEqual(parse(""), { kind: "ignore" });
    assert.deepEqual(parse(undefined), { kind: "ignore" });
    assert.deepEqual(parse(42), { kind: "ignore" });
  });

  it("the scheme is case-insensitive and a trailing slash is allowed", () => {
    assert.equal(parse(`VALORFINIS://auth/callback/?code=abc123`).kind, "code");
  });

  it("Expo Go / dev-client links are understood only when development links are allowed", () => {
    const url = "exp://192.168.1.5:8081/--/auth/callback?code=abc123";

    assert.deepEqual(parse(url), { kind: "ignore" });
    assert.equal(parse(url, { ...OPTIONS, allowExpoDevLinks: true }).kind, "code");
    assert.deepEqual(parse("exp://192.168.1.5:8081/--/goals", { ...OPTIONS, allowExpoDevLinks: true }), { kind: "ignore" });
  });
});

describe("valid links", () => {
  it("implicit flow: tokens in the fragment, recovery", () => {
    assert.deepEqual(parse(`${base}#access_token=${ACCESS}&refresh_token=${REFRESH}&expires_in=3600&token_type=bearer&type=recovery`), {
      kind: "session_tokens",
      purpose: "recovery",
      accessToken: ACCESS,
      refreshToken: REFRESH,
    });
  });

  it("implicit flow: confirmation (signup and email types)", () => {
    for (const type of ["signup", "email"]) {
      const link = parse(`${base}#access_token=${ACCESS}&refresh_token=${REFRESH}&type=${type}`);

      assert.equal(link.kind, "session_tokens");
      assert.equal(link.kind === "session_tokens" && link.purpose, "confirmation");
    }
  });

  it("tokens in the query string are understood too", () => {
    assert.equal(parse(`${base}?access_token=${ACCESS}&refresh_token=${REFRESH}&type=recovery`).kind, "session_tokens");
  });

  it("PKCE: a code", () => {
    assert.deepEqual(parse(`${base}?code=0a1b2c3d-4e5f`), { kind: "code", code: "0a1b2c3d-4e5f" });
  });

  it("token hash with a type", () => {
    assert.deepEqual(parse(`${base}?token_hash=abcdef1234567890&type=recovery`), {
      kind: "token_hash",
      purpose: "recovery",
      tokenHash: "abcdef1234567890",
      otpType: "recovery",
    });
    assert.equal(parse(`${base}?token_hash=abcdef1234567890&type=signup`).kind, "token_hash");
  });
});

describe("links the server reported as failed", () => {
  it("an expired or used link (otp_expired), in the fragment or the query", () => {
    const expired = { kind: "failed_link", reason: "expired" };

    assert.deepEqual(parse(`${base}#error=access_denied&error_code=otp_expired&error_description=Email+link+is+invalid+or+has+expired`), expired);
    assert.deepEqual(parse(`${base}?error=access_denied&error_code=otp_expired`), expired);
  });

  it("denied and unknown errors", () => {
    assert.deepEqual(parse(`${base}#error=access_denied`), { kind: "failed_link", reason: "denied" });
    assert.deepEqual(parse(`${base}#error=server_error&error_code=unexpected_failure`), { kind: "failed_link", reason: "unknown" });
  });

  it("an error wins over credentials in the same link, and its text is never returned", () => {
    const result = parse(`${base}#error=access_denied&error_description=SECRET-TEXT&access_token=${ACCESS}&refresh_token=${REFRESH}&type=recovery`);

    assert.equal(result.kind, "failed_link");
    assert.doesNotMatch(JSON.stringify(result), /SECRET-TEXT|payload/);
  });
});

describe("malformed and unsupported links are refused, never guessed", () => {
  const cases: [string, string][] = [
    ["no credential at all", `${base}`],
    ["an empty fragment", `${base}#`],
    ["only an access token", `${base}#access_token=${ACCESS}&type=recovery`],
    ["only a refresh token", `${base}#refresh_token=${REFRESH}&type=recovery`],
    ["tokens without a type", `${base}#access_token=${ACCESS}&refresh_token=${REFRESH}`],
    ["a token with forbidden characters", `${base}#access_token=${encodeURIComponent("a b<script>")}&refresh_token=${REFRESH}&type=recovery`],
    ["a repeated key", `${base}#access_token=${ACCESS}&access_token=${ACCESS}&refresh_token=${REFRESH}&type=recovery`],
    ["the same key in query and fragment", `${base}?type=recovery#access_token=${ACCESS}&refresh_token=${REFRESH}&type=recovery`],
    ["a bad percent escape", `${base}#access_token=%E0%A4%A&refresh_token=${REFRESH}&type=recovery`],
    ["a code with forbidden characters", `${base}?code=${encodeURIComponent("../../x")}`],
    ["a token hash that is too short", `${base}?token_hash=abc&type=recovery`],
    ["a token hash without a type", `${base}?token_hash=abcdef1234567890`],
  ];

  for (const [name, url] of cases) {
    it(name, () => {
      assert.deepEqual(parse(url), { kind: "invalid", reason: "malformed" });
    });
  }

  it("an oversized URL", () => {
    assert.deepEqual(parse(`${base}#access_token=${"a".repeat(9000)}&refresh_token=${REFRESH}&type=recovery`), { kind: "invalid", reason: "malformed" });
  });

  it("too many parameters", () => {
    const many = Array.from({ length: 30 }, (_, index) => `k${index}=v`).join("&");

    assert.deepEqual(parse(`${base}#${many}`), { kind: "invalid", reason: "malformed" });
  });

  it("invites, magic links and e-mail changes are unsupported and their tokens are not offered", () => {
    for (const type of ["invite", "magiclink", "email_change", "reauthentication", "unknown"]) {
      assert.deepEqual(parse(`${base}#access_token=${ACCESS}&refresh_token=${REFRESH}&type=${type}`), { kind: "invalid", reason: "unsupported" });
    }

    assert.deepEqual(parse(`${base}?token_hash=abcdef1234567890&type=magiclink`), { kind: "invalid", reason: "unsupported" });
  });

  it("a refusal never carries part of the URL", () => {
    const result = parse(`${base}#access_token=${ACCESS}&type=recovery`);

    assert.doesNotMatch(JSON.stringify(result), /payload|signature/);
  });
});

describe("the app's URL scheme", () => {
  it("is app-specific, valid for iOS and Android, and builds the redirect URL", () => {
    assert.equal(isAppSpecificScheme("valorfinis"), true);
    assert.equal(buildAuthRedirectUrl("valorfinis"), `valorfinis://${AUTH_CALLBACK_PATH}`);
    assert.equal(parse(buildAuthRedirectUrl("valorfinis")).kind, "invalid", "the bare redirect URL is ours but carries nothing");
  });

  it("rejects the generic and malformed values", () => {
    for (const bad of ["mobile", "app", "exp", "http", "https", "Valor", "1abc", "ab", "has space", "", undefined, 5]) {
      assert.equal(isAppSpecificScheme(bad), false, String(bad));
    }
  });

  it("app.json declares an app-specific scheme (not the scaffold's generic one)", () => {
    const config = JSON.parse(readFileSync("app.json", "utf8")) as { expo: { scheme?: unknown } };

    assert.equal(isAppSpecificScheme(config.expo.scheme), true);
    assert.equal(config.expo.scheme, "valorfinis");
  });
});
