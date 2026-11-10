// MF-4: turning auth links into sessions: cold start, running app, expired,
// replayed, malformed and unsupported links, concurrent links, identity changes,
// and the rule that a failed link never releases a recovery session. Fakes only.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { createAuthLinkHandler, type LinkAuth, type LinkOutcome } from "./auth-link-handler.ts";
import { createRecoveryState } from "./recovery-state.ts";

const SECRET = "SECRET-CODE-VALUE";
const base = "valorfinis://auth/callback";
// A PKCE link; the fake exchange treats codes that start with "recovery" as recovery codes.
const recoveryLink = (n = 1) => `${base}?code=recovery-${SECRET}-${n}`;
const confirmLink = (n = 1) => `${base}?code=confirm-${SECRET}-${n}`;
const implicitLink = `${base}#access_token=eyJhbGciOiJIUzI1NiJ9.${SECRET}.sig&refresh_token=${SECRET}&type=recovery`;
const hashLink = `${base}?token_hash=${SECRET}abcdef&type=recovery`;

type Gate<T> = { promise: Promise<T>; resolve: (value: T) => void };
function gate<T>(): Gate<T> {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((done) => { resolve = done; });

  return { promise, resolve };
}

type Result = Awaited<ReturnType<LinkAuth["exchangeCodeForSession"]>>;
const ok = (userId: string, redirectType: string | null = null): Result => ({ data: { session: { user: { id: userId } }, redirectType }, error: null });
const fail = (error: unknown): Result => ({ data: null, error });

function world(
  exchange?: (code: string) => Promise<Result>,
  // Runs right after the auth client stored the session: models what happens
  // between "the session exists" and "the handler looks at it".
  afterSessionSet?: (state: { current: string | null }) => void,
) {
  const calls: string[] = [];
  const state = { current: null as string | null };
  const recovery = createRecoveryState();
  const auth: LinkAuth = {
    exchangeCodeForSession: async (code) => {
      calls.push(code);

      const result = exchange ? await exchange(code) : ok("user-a", code.startsWith("recovery") ? "recovery" : null);

      if (result.data?.session) {
        state.current = result.data.session.user.id;
        afterSessionSet?.(state);
      }

      return result;
    },
  };
  const handler = createAuthLinkHandler({
    parse: { schemes: ["valorfinis"] },
    auth,
    currentUserId: () => state.current,
    recovery,
  });

  return { handler, recovery, calls, state };
}

const kinds = (outcome: LinkOutcome | null) => outcome?.kind;

describe("recovery link", () => {
  it("a valid link activates the recovery of its user and publishes one notice", async () => {
    const w = world();

    assert.equal(w.handler.receive(recoveryLink()), true);
    assert.equal(w.recovery.getSnapshot().phase, "verifying", "the UI is told at once");

    const outcome = await w.handler.drain();

    assert.deepEqual(outcome, { kind: "recovery_ready", userId: "user-a" });
    assert.deepEqual(w.recovery.getSnapshot(), { phase: "active", userId: "user-a" });
    assert.equal(w.handler.getNotice()?.outcome.kind, "recovery_ready");
    assert.deepEqual(w.calls, [`recovery-${SECRET}-1`]);
  });

  it("the purpose comes from the exchange: auth-js reports 'recovery' (and the event name is accepted too)", async () => {
    for (const [redirectType, expected] of [["recovery", "recovery_ready"], ["PASSWORD_RECOVERY", "recovery_ready"], [null, "confirmed"], ["signup", "confirmed"], ["", "confirmed"]] as const) {
      const w = world(async () => ok("user-a", redirectType));

      w.handler.receive(`${base}?code=any-code-1`);
      assert.equal(kinds(await w.handler.drain()), expected, String(redirectType));
    }
  });

  it("cold start: received before authentication is ready, processed only when drained", async () => {
    const w = world();

    w.handler.receive(recoveryLink());
    assert.equal(w.calls.length, 0, "nothing runs before the host drains");
    assert.equal(w.handler.hasPending(), true);
    assert.equal(kinds(await w.handler.drain()), "recovery_ready");
    assert.equal(w.handler.hasPending(), false);
  });

  it("already running: a link that arrives later notifies the host", async () => {
    const w = world();
    let notified = 0;

    w.handler.subscribePending(() => { notified += 1; });
    w.handler.receive(recoveryLink());
    assert.equal(notified, 1);
    await w.handler.drain();
  });

  it("a link that is not ours is not claimed and changes nothing", async () => {
    const w = world();

    assert.equal(w.handler.receive("valorfinis://goals/1"), false);
    assert.equal(w.handler.receive("mobile://auth/callback?code=abc-123"), false);
    assert.equal(w.recovery.getSnapshot().phase, "idle");
    assert.equal(await w.handler.drain(), null);
  });

  it("the same URL delivered twice (initial URL plus event) is processed once", async () => {
    const w = world();

    assert.equal(w.handler.receive(recoveryLink()), true);
    assert.equal(w.handler.receive(recoveryLink()), true);
    await w.handler.drain();
    assert.equal(w.calls.length, 1);
    assert.equal(await w.handler.drain(), null);
  });

  it("the same URL delivered while the first is in flight is ignored", async () => {
    const hold = gate<Result>();
    const w = world(() => hold.promise);

    w.handler.receive(recoveryLink());

    const first = w.handler.drain();

    assert.equal(w.handler.receive(recoveryLink()), true);
    assert.equal(w.handler.hasPending(), false, "no second attempt is queued");
    hold.resolve(ok("user-a", "recovery"));
    assert.equal(kinds(await first), "recovery_ready");
    assert.equal(w.calls.length, 1);
  });
});

describe("expired, replayed, malformed and refused links", () => {
  it("a replay of a used link says 'invalid or expired' without calling the server", async () => {
    const w = world();

    w.handler.receive(recoveryLink());
    await w.handler.drain();
    w.recovery.complete("user-a");
    w.handler.receive(recoveryLink());
    assert.equal(w.recovery.getSnapshot().phase, "idle", "a replay does not even close the gate");

    const outcome = await w.handler.drain();

    assert.deepEqual(outcome, { kind: "link_invalid", reason: "expired_or_used" });
    assert.equal(w.calls.length, 1);
    assert.equal(w.recovery.getSnapshot().phase, "idle");
  });

  it("the server rejecting the code (already used, expired, or no verifier on this device)", async () => {
    for (const error of [
      { name: "AuthApiError", code: "flow_state_not_found", status: 404 },
      { name: "AuthApiError", code: "otp_expired", status: 403 },
      { name: "AuthPKCECodeVerifierMissingError", status: 400 },
    ]) {
      const w = world(async () => fail(error));

      w.handler.receive(recoveryLink());
      assert.deepEqual(await w.handler.drain(), { kind: "link_invalid", reason: "expired_or_used" });
      assert.equal(w.recovery.getSnapshot().phase, "idle");
    }
  });

  it("an error link reported by the server never reaches the auth client", async () => {
    const w = world();

    w.handler.receive(`${base}#error=access_denied&error_code=otp_expired&error_description=Email+link+is+invalid`);
    assert.deepEqual(await w.handler.drain(), { kind: "link_invalid", reason: "expired_or_used" });
    assert.equal(w.calls.length, 0);
  });

  it("a malformed link never reaches the auth client", async () => {
    const w = world();

    w.handler.receive(`${base}#access_token=abc&type=recovery`);
    assert.deepEqual(await w.handler.drain(), { kind: "link_invalid", reason: "malformed" });
    assert.equal(w.calls.length, 0);
  });

  it("session-carrying and token-hash links are refused (login CSRF): no auth call, no state change", async () => {
    for (const link of [implicitLink, hashLink, `${base}#access_token=a.b.c&refresh_token=r&type=signup`]) {
      const w = world();

      assert.equal(w.handler.receive(link), true);
      assert.equal(w.recovery.getSnapshot().phase, "idle", "the gate is not even closed");
      assert.deepEqual(await w.handler.drain(), { kind: "link_invalid", reason: "unsupported" });
      assert.equal(w.calls.length, 0);
    }
  });

  it("when the server is unreachable the link is not consumed: opening it again retries", async () => {
    let attempt = 0;
    const w = world(async () => {
      attempt += 1;

      return attempt === 1 ? fail({ name: "AuthRetryableFetchError", status: 0 }) : ok("user-a", "recovery");
    });

    w.handler.receive(recoveryLink());
    assert.deepEqual(await w.handler.drain(), { kind: "unavailable" });
    assert.equal(w.recovery.getSnapshot().phase, "idle");

    w.handler.receive(recoveryLink());
    assert.equal(kinds(await w.handler.drain()), "recovery_ready");
    assert.equal(w.calls.length, 2);
  });

  it("an unexpected exception is 'unavailable', never a guess, and carries no text", async () => {
    const w = world(async () => { throw new Error(`boom with ${SECRET}`); });

    w.handler.receive(recoveryLink());

    const outcome = await w.handler.drain();

    assert.deepEqual(outcome, { kind: "unavailable" });
    assert.doesNotMatch(JSON.stringify([outcome, w.handler.getNotice()]), /SECRET/);
    assert.equal(w.recovery.getSnapshot().phase, "idle");
  });

  it("a session without a user is 'invalid or expired'", async () => {
    const w = world(async () => ({ data: { session: null }, error: null }));

    w.handler.receive(recoveryLink());
    assert.equal(kinds(await w.handler.drain()), "link_invalid");
  });
});

describe("a failed link never releases a recovery session into the app", () => {
  async function activeRecovery() {
    const w = world();

    w.handler.receive(recoveryLink(1));
    await w.handler.drain();
    assert.deepEqual(w.recovery.getSnapshot(), { phase: "active", userId: "user-a" });

    return w;
  }

  const junk: [string, string][] = [
    ["a bare link", base],
    ["a malformed link", `${base}#access_token=abc&type=recovery`],
    ["an expired link", `${base}#error=access_denied&error_code=otp_expired`],
    ["an implicit link", implicitLink],
    ["a token-hash link", hashLink],
  ];

  for (const [name, link] of junk) {
    it(`${name}: the recovery stays active and the gate never opens`, async () => {
      const w = await activeRecovery();
      const seen: string[] = [];

      w.recovery.subscribe(() => seen.push(w.recovery.getSnapshot().phase));
      w.handler.receive(link);
      await w.handler.drain();
      assert.deepEqual(w.recovery.getSnapshot(), { phase: "active", userId: "user-a" });
      assert.deepEqual(seen, [], "no state change at all");
    });
  }

  it("a replay of the used link: the recovery stays active", async () => {
    const w = await activeRecovery();

    w.handler.receive(recoveryLink(1));
    await w.handler.drain();
    assert.deepEqual(w.recovery.getSnapshot(), { phase: "active", userId: "user-a" });
  });

  it("a new code that the server rejects: the earlier recovery is restored, not dropped", async () => {
    let call = 0;
    const w = world(async () => (++call === 1 ? ok("user-a", "recovery") : fail({ name: "AuthApiError", code: "flow_state_not_found" })));

    w.handler.receive(recoveryLink(1));
    await w.handler.drain();
    w.handler.receive(recoveryLink(2));
    assert.equal(w.recovery.getSnapshot().phase, "verifying");
    assert.equal(kinds(await w.handler.drain()), "link_invalid");
    assert.deepEqual(w.recovery.getSnapshot(), { phase: "active", userId: "user-a" });
  });

  it("a first recovery still in flight when a second (failing) link finishes first: the recovery session stays gated", async () => {
    const holds = [gate<Result>(), gate<Result>()];
    let index = 0;
    const w = world(() => holds[index++].promise);

    w.handler.receive(recoveryLink(1));

    const first = w.handler.drain();

    w.handler.receive(recoveryLink(2));

    const second = w.handler.drain();

    holds[1].resolve(fail({ name: "AuthApiError", code: "otp_expired" }));
    assert.equal(kinds(await second), "link_invalid");
    holds[0].resolve(ok("user-a", "recovery"));
    assert.deepEqual(await first, { kind: "stale" });
    assert.deepEqual(w.recovery.getSnapshot(), { phase: "active", userId: "user-a" }, "the stored recovery session did not fall through to the app");
  });

  it("the second link fails AFTER the first stored its recovery session: still gated", async () => {
    const holds = [gate<Result>(), gate<Result>()];
    let index = 0;
    const w = world(() => holds[index++].promise);

    w.handler.receive(recoveryLink(1));

    const first = w.handler.drain();

    w.handler.receive(recoveryLink(2));

    const second = w.handler.drain();

    holds[0].resolve(ok("user-a", "recovery"));
    assert.deepEqual(await first, { kind: "stale" });
    holds[1].resolve(fail({ name: "AuthApiError", code: "otp_expired" }));
    await second;
    assert.deepEqual(w.recovery.getSnapshot(), { phase: "active", userId: "user-a" });
  });

  it("a pending link that is replaced before it starts releases the gate it closed", async () => {
    const w = world();

    w.handler.receive(recoveryLink(1));
    assert.equal(w.recovery.getSnapshot().phase, "verifying");
    w.handler.receive(base); // a bare link replaces it
    assert.equal(w.recovery.getSnapshot().phase, "idle", "the gate is not left closed");
    await w.handler.drain();
    assert.equal(w.recovery.getSnapshot().phase, "idle");
  });
});

describe("concurrent links and identity changes", () => {
  it("the newest link wins; an older attempt that resolves late applies nothing", async () => {
    const holds = [gate<Result>(), gate<Result>()];
    let index = 0;
    const w = world(() => holds[index++].promise);

    w.handler.receive(recoveryLink(1));

    const older = w.handler.drain();

    w.handler.receive(recoveryLink(2));

    const newer = w.handler.drain();

    holds[1].resolve(ok("user-b", "recovery"));
    assert.deepEqual(await newer, { kind: "recovery_ready", userId: "user-b" });
    holds[0].resolve(ok("user-a", "recovery"));
    assert.deepEqual(await older, { kind: "stale" });
    assert.equal(w.handler.getNotice()?.outcome.kind, "recovery_ready", "a stale result publishes nothing");
  });

  it("a link replaced before it started is not marked used", async () => {
    const w = world();

    w.handler.receive(recoveryLink(1));
    w.handler.receive(recoveryLink(2));
    await w.handler.drain();
    w.recovery.complete("user-a");
    w.handler.receive(recoveryLink(1));
    assert.equal(kinds(await w.handler.drain()), "recovery_ready", "the first link was never used");
  });

  it("somebody else signed in before the result was applied: stale, no recovery", async () => {
    const w = world(undefined, (state) => { state.current = "user-b"; });

    w.handler.receive(recoveryLink());
    assert.deepEqual(await w.handler.drain(), { kind: "stale" });
    assert.equal(w.recovery.getSnapshot().phase, "idle");
  });

  it("signed out right after the session was established: stale, no recovery", async () => {
    const w = world(undefined, (state) => { state.current = null; });

    w.handler.receive(recoveryLink());
    assert.deepEqual(await w.handler.drain(), { kind: "stale" });
    assert.equal(w.recovery.getSnapshot().phase, "idle");
  });

  it("a recovery that is active is replaced, not merged, by a link for another user", async () => {
    const results = [ok("user-a", "recovery"), ok("user-b", "recovery")];
    let index = 0;
    const w = world(async () => results[index++]);

    w.handler.receive(recoveryLink(1));
    await w.handler.drain();
    w.handler.receive(recoveryLink(2));
    await w.handler.drain();
    assert.deepEqual(w.recovery.getSnapshot(), { phase: "active", userId: "user-b" });
  });
});

describe("confirmation links", () => {
  it("a confirmation code yields a normal session, not a recovery", async () => {
    const w = world();

    w.handler.receive(confirmLink());
    assert.deepEqual(await w.handler.drain(), { kind: "confirmed" });
    assert.equal(w.recovery.getSnapshot().phase, "idle");
  });
});

describe("notices and secrets", () => {
  it("a notice is shown once and acknowledged by id", async () => {
    const w = world();
    let changes = 0;

    w.handler.subscribeNotice(() => { changes += 1; });
    w.handler.receive(confirmLink());
    await w.handler.drain();

    const notice = w.handler.getNotice();

    assert.ok(notice);
    w.handler.acknowledge(notice.id + 1);
    assert.ok(w.handler.getNotice(), "a wrong id does not clear it");
    w.handler.acknowledge(notice.id);
    assert.equal(w.handler.getNotice(), null);
    assert.equal(changes, 2);
  });

  it("no outcome or notice ever contains a credential or part of the URL", async () => {
    const outcomes: unknown[] = [];

    for (const link of [recoveryLink(), `${base}#error=access_denied&error_description=${SECRET}`, implicitLink, hashLink, confirmLink()]) {
      const w = world();

      w.handler.receive(link);
      outcomes.push(await w.handler.drain(), w.handler.getNotice());
    }

    assert.doesNotMatch(JSON.stringify(outcomes), /SECRET|eyJhbGci|access_token|refresh_token|token_hash/);
  });
});
