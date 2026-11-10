// MF-4: sign-up, password-reset request and resend flows with fake Supabase
// responses. Covers success/failure, confirmation on/off, existing-email responses
// without enumeration, rapid repeated submissions and secret-free messages.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AUTH_NETWORK_MESSAGE,
  AUTH_RATE_LIMIT_MESSAGE,
  RESEND_COOLDOWN_SECONDS,
  createSubmitGuard,
  registerAccount,
  requestPasswordReset,
  resendConfirmation,
  resendSecondsLeft,
  validateEmail,
  validateNewPassword,
  validateResetForm,
  validateSignUpForm,
  type SignUpOutcome,
} from "./auth-registration.ts";

const REDIRECT = "valorfinis://auth/callback";
const PASSWORD = "correct horse battery";
const api = (code: string, status = 400) => ({ name: "AuthApiError", code, status, message: `SERVER: ${code} for person@example.test password=${PASSWORD}` });

type SignUpResponse = Awaited<ReturnType<Parameters<typeof registerAccount>[0]["signUp"]>>;

function signUpWorld(respond: () => Promise<SignUpResponse> | SignUpResponse, current = true) {
  const calls: unknown[] = [];
  const state = { current };
  const deps = {
    signUp: async (params: unknown) => {
      calls.push(params);

      return respond();
    },
    redirectTo: REDIRECT,
    isCurrent: () => state.current,
  };

  return { calls, state, run: (email = "  Person@Example.test ", password = PASSWORD) => registerAccount(deps, { email, password }) };
}

const session = { data: { session: { user: { id: "u" } } }, error: null };
const noSession = { data: { session: null }, error: null };

describe("validation", () => {
  it("email", () => {
    assert.equal(validateEmail(""), "Enter your email address.");
    assert.equal(validateEmail("   "), "Enter your email address.");
    assert.equal(validateEmail("not-an-email"), "Enter a valid email address.");
    assert.equal(validateEmail("a@b"), "Enter a valid email address.");
    assert.equal(validateEmail(`${"a".repeat(250)}@b.co`), "Enter a valid email address.");
    assert.equal(validateEmail(" person@example.test "), null);
  });

  it("password length bounds", () => {
    assert.equal(validateNewPassword(""), "Enter a password.");
    assert.equal(validateNewPassword("short"), "Use at least 8 characters.");
    assert.equal(validateNewPassword("x".repeat(73)), "Use at most 72 characters.");
    assert.equal(validateNewPassword("x".repeat(8)), null);
    assert.equal(validateNewPassword("x".repeat(72)), null);
  });

  it("sign-up form: reports every problem, confirmation checked only once the password is valid", () => {
    assert.deepEqual(validateSignUpForm({ email: "", password: "", confirm: "" }), { email: "Enter your email address.", password: "Enter a password." });
    assert.deepEqual(validateSignUpForm({ email: "a@b.co", password: PASSWORD, confirm: "different" }), { confirm: "The passwords do not match." });
    assert.deepEqual(validateSignUpForm({ email: "a@b.co", password: PASSWORD, confirm: PASSWORD }), {});
  });

  it("reset form", () => {
    assert.deepEqual(validateResetForm({ password: "short", confirm: "short" }), { password: "Use at least 8 characters." });
    assert.deepEqual(validateResetForm({ password: PASSWORD, confirm: "nope" }), { confirm: "The passwords do not match." });
    assert.deepEqual(validateResetForm({ password: PASSWORD, confirm: PASSWORD }), {});
  });
});

describe("registration outcomes", () => {
  it("confirmation NOT required: a session comes back, the user is signed in", async () => {
    const w = signUpWorld(() => session);

    assert.deepEqual(await w.run(), { kind: "signed_in" });
  });

  it("confirmation required: no session, 'check your email'; the address is trimmed and the redirect URL is sent", async () => {
    const w = signUpWorld(() => noSession);

    assert.deepEqual(await w.run(), { kind: "check_email", email: "Person@Example.test" });
    assert.deepEqual(w.calls, [{ email: "Person@Example.test", password: PASSWORD, options: { emailRedirectTo: REDIRECT } }]);
  });

  it("an existing address looks exactly like a new one when confirmation is required", async () => {
    const fresh = await signUpWorld(() => noSession).run();
    // Supabase with enumeration protection answers an existing address with success and no session.
    const existingQuiet = await signUpWorld(() => ({ data: { session: null }, error: null })).run();
    // Without enumeration protection it answers with an error code.
    const existingLoud = await signUpWorld(() => ({ data: null, error: api("user_already_exists", 422) })).run();
    const existingLoud2 = await signUpWorld(() => ({ data: null, error: api("email_exists", 422) })).run();

    assert.deepEqual(existingQuiet, fresh);
    assert.deepEqual(existingLoud, fresh);
    assert.deepEqual(existingLoud2, fresh);
  });

  it("failures: weak password, invalid email, rate limit, network, disabled, unknown", async () => {
    const run = (error: unknown) => signUpWorld(() => ({ data: null, error })).run();

    assert.deepEqual(await run(api("weak_password", 422)), { kind: "rejected", field: "password", message: "That password is not strong enough. Try a longer one with a mix of characters." });
    assert.deepEqual(await run({ name: "AuthWeakPasswordError", code: "weak_password", reasons: ["length", "pwned"] }), {
      kind: "rejected",
      field: "password",
      message: "That password is not strong enough: make it longer, avoid a password that appeared in a data leak.",
    });
    assert.deepEqual(await run(api("email_address_invalid")), { kind: "rejected", field: "email", message: "Enter a valid email address." });
    assert.deepEqual(await run(api("over_email_send_rate_limit", 429)), { kind: "failed", message: AUTH_RATE_LIMIT_MESSAGE });
    assert.deepEqual(await run({ name: "AuthRetryableFetchError", status: 0 }), { kind: "failed", message: AUTH_NETWORK_MESSAGE });
    assert.deepEqual(await run(api("signup_disabled", 422)), { kind: "failed", message: "Creating accounts is not available right now." });
    assert.deepEqual(await run(api("mystery")), { kind: "failed", message: "We could not create your account. Please try again." });
  });

  it("a thrown error is a failure, not a crash", async () => {
    const w = signUpWorld(() => { throw new Error(`boom ${PASSWORD}`); });

    assert.deepEqual(await w.run(), { kind: "failed", message: "We could not create your account. Please try again." });
  });

  it("no message ever carries the server's text, the address or the password", async () => {
    const outcomes: SignUpOutcome[] = [];

    for (const code of ["weak_password", "email_address_invalid", "over_email_send_rate_limit", "signup_disabled", "mystery", "user_already_exists"]) {
      outcomes.push(await signUpWorld(() => ({ data: null, error: api(code) })).run());
    }

    outcomes.push(await signUpWorld(() => { throw new Error(PASSWORD); }).run());

    const text = JSON.stringify(outcomes.filter((outcome) => outcome.kind !== "check_email"));

    assert.doesNotMatch(text, /SERVER|person@example|correct horse|password=/i);
  });

  it("an answer that arrives after the user left or changed is dropped", async () => {
    const w = signUpWorld(async () => { w.state.current = false; return session; });

    assert.deepEqual(await w.run(), { kind: "stale" });
  });

  it("rapid repeated submissions: the guard lets exactly one call through", async () => {
    let release: (value: SignUpResponse) => void = () => undefined;
    const w = signUpWorld(() => new Promise<SignUpResponse>((resolve) => { release = resolve; }));
    const guard = createSubmitGuard();
    const submit = async () => {
      if (!guard.tryStart()) {
        return "ignored" as const;
      }

      try {
        return await w.run();
      } finally {
        guard.end();
      }
    };
    const attempts = [submit(), submit(), submit()];

    release(noSession);
    assert.deepEqual(await Promise.all(attempts), [{ kind: "check_email", email: "Person@Example.test" }, "ignored", "ignored"]);
    assert.equal(w.calls.length, 1);

    const again = submit();

    release(noSession);
    assert.deepEqual(await again, { kind: "check_email", email: "Person@Example.test" }, "usable again once finished");
    assert.equal(w.calls.length, 2);
  });

  it("never retries by itself: one call per action, also on failure", async () => {
    const w = signUpWorld(() => ({ data: null, error: { name: "AuthRetryableFetchError", status: 0 } }));

    await w.run();
    assert.equal(w.calls.length, 1);
  });
});

describe("password reset request and resend", () => {
  type Plain = { error: unknown };
  const resetWorld = (respond: () => Plain | Promise<Plain>, current = true) => {
    const calls: unknown[] = [];

    return {
      calls,
      run: (email = " person@example.test ") =>
        requestPasswordReset(
          { resetPasswordForEmail: async (address, options) => { calls.push([address, options]); return respond(); }, redirectTo: REDIRECT, isCurrent: () => current },
          email,
        ),
    };
  };

  it("sends the trimmed address and the redirect URL; the outcome is the same for any address", async () => {
    const known = resetWorld(() => ({ error: null }));
    const unknown = resetWorld(() => ({ error: null }));

    assert.deepEqual(await known.run(), { kind: "sent", email: "person@example.test" });
    assert.deepEqual(await unknown.run("someone-else@example.test"), { kind: "sent", email: "someone-else@example.test" });
    assert.deepEqual(known.calls, [["person@example.test", { redirectTo: REDIRECT }]]);
  });

  it("an account-related refusal looks like success (no enumeration)", async () => {
    assert.equal((await resetWorld(() => ({ error: api("user_not_found", 404) })).run()).kind, "sent");
    assert.equal((await resetWorld(() => ({ error: api("user_already_exists", 422) })).run()).kind, "sent");
  });

  it("an invalid address, a rate limit, a network failure and an unknown failure are reported", async () => {
    assert.deepEqual(await resetWorld(() => ({ error: api("validation_failed") })).run(), { kind: "rejected", message: "Enter a valid email address." });
    assert.deepEqual(await resetWorld(() => ({ error: api("over_email_send_rate_limit", 429) })).run(), { kind: "failed", message: AUTH_RATE_LIMIT_MESSAGE });
    assert.deepEqual(await resetWorld(() => ({ error: { name: "AuthRetryableFetchError", status: 0 } })).run(), { kind: "failed", message: AUTH_NETWORK_MESSAGE });
    assert.deepEqual(await resetWorld(() => ({ error: api("mystery") })).run(), { kind: "failed", message: "We could not send the link. Please try again." });
    assert.deepEqual(await resetWorld(() => { throw new Error("SERVER person@example.test"); }).run(), { kind: "failed", message: "We could not send the link. Please try again." });
  });

  it("a late answer is dropped", async () => {
    assert.deepEqual(await resetWorld(() => ({ error: null }), false).run(), { kind: "stale" });
  });

  it("resend uses the signup type and the redirect URL, with the same neutral outcome", async () => {
    const calls: unknown[] = [];
    const run = (error: unknown) =>
      resendConfirmation(
        { resend: async (params) => { calls.push(params); return { error }; }, redirectTo: REDIRECT, isCurrent: () => true },
        "person@example.test",
      );

    assert.deepEqual(await run(null), { kind: "sent", email: "person@example.test" });
    assert.deepEqual(await run(api("user_already_exists", 422)), { kind: "sent", email: "person@example.test" });
    assert.deepEqual(calls[0], { type: "signup", email: "person@example.test", options: { emailRedirectTo: REDIRECT } });
    assert.deepEqual(await run(api("mystery")), { kind: "failed", message: "We could not send the email. Please try again." });
  });
});

describe("resend cooldown", () => {
  it("counts down from the cooldown to zero and never goes outside the range", () => {
    assert.equal(resendSecondsLeft(null, 1_000), 0);
    assert.equal(resendSecondsLeft(1_000, 1_000), RESEND_COOLDOWN_SECONDS);
    assert.equal(resendSecondsLeft(1_000, 1_000 + 30_000), RESEND_COOLDOWN_SECONDS - 30);
    assert.equal(resendSecondsLeft(1_000, 1_000 + 60_000), 0);
    assert.equal(resendSecondsLeft(1_000, 1_000 + 600_000), 0);
    assert.equal(resendSecondsLeft(5_000, 1_000), RESEND_COOLDOWN_SECONDS, "a clock that went backwards");
  });
});
