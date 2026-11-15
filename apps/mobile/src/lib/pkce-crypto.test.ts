// MOBILE-002A: secure PKCE S256 for Supabase Auth on React Native.
// Real @supabase/supabase-js inside a runtime that matches what Hermes in Expo Go 57 really exposes (`crypto`
// undefined; TextEncoder and btoa present, measured on the iOS Simulator). Only the network, the storage and the
// native crypto primitives are faked. Values (verifier, codes, tokens) are never printed: assertions are booleans.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { webcrypto } from "node:crypto";
import { test } from "node:test";

import {
  guardAgainstPlainPkce,
  installPkceCrypto,
  PkceCryptoUnavailableError,
  type SecureCryptoPrimitives,
} from "./pkce-crypto.ts";
import { countMathRandomCalls, createRealClient, sha256Base64Url, withGlobalCrypto } from "./pkce-test-support.ts";

// Stand-in for the native expo-crypto functions, backed by Node's real SHA-256 / CSPRNG, counting bytes drawn.
function securePrimitives() {
  let randomBytes = 0;
  const primitives: SecureCryptoPrimitives = {
    getRandomValues: (array) => {
      randomBytes += array.byteLength;
      return webcrypto.getRandomValues(array as never) as typeof array;
    },
    digestSha256: (data) => webcrypto.subtle.digest("SHA-256", data),
  };

  return { primitives, randomBytesDrawn: () => randomBytes };
}

async function silenced<T>(run: () => Promise<T>): Promise<{ result: T; warnings: string[] }> {
  const original = console.warn;
  const warnings: string[] = [];

  console.warn = (message: unknown) => void warnings.push(String(message));
  try {
    return { result: await run(), warnings };
  } finally {
    console.warn = original;
  }
}

const hermesLikeRuntime = <T>(run: () => Promise<T>) => withGlobalCrypto(undefined, run);

test("defect baseline: WITHOUT the fix, auth-js in a Hermes-like runtime sends plain and draws randomness from Math.random", async () => {
  await hermesLikeRuntime(async () => {
    const real = createRealClient();
    const { result: { calls }, warnings } = await silenced(() => countMathRandomCalls(() => real.signUp()));
    const body = real.requests[0].body;

    assert.equal(body.code_challenge_method, "plain");
    assert.ok(body.code_challenge === real.storedVerifier(), "plain: the challenge IS the verifier");
    assert.ok(calls >= 56, "verifier and flow id come from Math.random");
    assert.ok(warnings.some((message) => message.includes("WebCrypto API is not supported")));
  });
});

test("A/B/C: with the fix the verifier is drawn from the secure primitive, the challenge is SHA-256(verifier) and the method is S256", async () => {
  await hermesLikeRuntime(async () => {
    const { primitives, randomBytesDrawn } = securePrimitives();

    assert.equal(installPkceCrypto(globalThis, primitives), true);

    const real = createRealClient();
    const { calls } = await countMathRandomCalls(() => real.signUp());
    const body = real.requests[0].body;
    const verifier = real.storedVerifier();

    assert.equal(calls, 0, "Math.random is never used");
    assert.ok(randomBytesDrawn() >= 56 * 4, "verifier randomness came from the secure primitive");
    assert.ok(verifier !== null && verifier.length === 112 && /^[0-9a-f]+$/.test(verifier), "56 random bytes, hex encoded (43..128 chars)");
    assert.equal(body.code_challenge_method, "s256");
    assert.ok(body.code_challenge === sha256Base64Url(verifier ?? ""), "challenge === base64url(SHA-256(verifier)), computed independently");
    assert.ok(body.code_challenge !== verifier, "the verifier itself is never sent");

    const second = createRealClient();

    await second.signUp();
    assert.ok(second.storedVerifier() !== verifier, "every flow gets a fresh verifier");
  });
});

test("F: the real code exchange works: the server-side check SHA-256(code_verifier) === code_challenge passes", async () => {
  await hermesLikeRuntime(async () => {
    installPkceCrypto(globalThis, securePrimitives().primitives);

    let serverChallengeMatched: boolean | null = null;
    let sentChallenge = "";
    const fakeJwt = `${Buffer.from("{}").toString("base64url")}.${Buffer.from('{"exp":4102444800}').toString("base64url")}.fake`;
    const real = createRealClient((inner) => async (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const body = typeof init?.body === "string" ? (JSON.parse(init.body) as Record<string, string>) : {};

      if (url.includes("/signup")) {
        sentChallenge = body.code_challenge;
      }

      if (url.includes("grant_type=pkce")) {
        serverChallengeMatched = sha256Base64Url(body.code_verifier) === sentChallenge;

        return new Response(
          JSON.stringify({
            access_token: fakeJwt,
            refresh_token: "fake-refresh",
            expires_in: 3600,
            token_type: "bearer",
            user: { id: "00000000-0000-4000-8000-000000000001", aud: "authenticated", email: "fake@example.test" },
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }

      return inner(input, init);
    });

    await real.signUp();

    const { data, error } = await real.client.auth.exchangeCodeForSession("fake-one-time-code");

    assert.equal(error, null);
    assert.equal(serverChallengeMatched, true);
    assert.ok(data.session !== null, "a session is established");
  });
});

test("E: missing or misbehaving secure crypto fails closed: nothing is sent, never plain", async () => {
  const broken: [string, SecureCryptoPrimitives][] = [
    ["random primitive throws", { getRandomValues: () => { throw new Error("native module unavailable"); }, digestSha256: securePrimitives().primitives.digestSha256 }],
    ["digest primitive throws", { getRandomValues: securePrimitives().primitives.getRandomValues, digestSha256: async () => { throw new Error("native module unavailable"); } }],
    ["digest has the wrong length", { getRandomValues: securePrimitives().primitives.getRandomValues, digestSha256: async () => new ArrayBuffer(8) }],
  ];

  for (const [label, primitives] of broken) {
    await hermesLikeRuntime(async () => {
      installPkceCrypto(globalThis, primitives);

      const real = createRealClient();
      const outcome = await real.signUp().then((value) => value.error, (thrown: unknown) => thrown);

      assert.ok(outcome, `${label}: sign-up must fail`);
      assert.equal(real.requests.length, 0, `${label}: no request leaves the device`);
    });
  }
});

test("E: the installed shim rejects unsupported use instead of guessing", async () => {
  await hermesLikeRuntime(async () => {
    installPkceCrypto(globalThis, securePrimitives().primitives);

    const shim = globalThis.crypto;

    assert.throws(() => shim.getRandomValues(new Float64Array(2)), TypeError);
    assert.throws(() => shim.getRandomValues(new Uint8Array(65_537)), RangeError);
    await assert.rejects(() => shim.subtle.digest("SHA-512", new Uint8Array(1)), PkceCryptoUnavailableError);
    assert.equal((await shim.subtle.digest({ name: "sha-256" }, new Uint8Array(1))).byteLength, 32);
  });
});

test("D: if the plain method ever reaches the network layer it is refused before anything is sent", async () => {
  await hermesLikeRuntime(async () => {
    // Deliberately NO shim: the unfixed runtime, but the app's fetch guard is in place.
    const real = createRealClient((inner) => guardAgainstPlainPkce(inner));
    const outcome = await silenced(() => real.signUp().then((value) => value.error, (thrown: unknown) => thrown));

    assert.ok(outcome.result, "sign-up is refused");
    assert.equal(real.requests.length, 0, "the plain request was never sent");
  });

  const sent: string[] = [];
  const guarded = guardAgainstPlainPkce(async (input) => {
    sent.push(String(input));
    return new Response("{}");
  });

  await guarded("http://127.0.0.1:54321/auth/v1/signup", { method: "POST", body: JSON.stringify({ code_challenge_method: "s256" }) });
  await guarded("http://127.0.0.1:54321/auth/v1/user");
  await assert.rejects(() => guarded("http://127.0.0.1:54321/auth/v1/authorize?code_challenge_method=plain&x=1"), PkceCryptoUnavailableError);
  await assert.rejects(() => guarded("http://127.0.0.1:54321/x", { method: "POST", body: '{"code_challenge_method": "PLAIN"}' }), PkceCryptoUnavailableError);
  assert.equal(sent.length, 2, "S256 and non-PKCE requests pass through");
});

test("H: where a complete native WebCrypto exists (web) nothing is replaced and the library uses it", async () => {
  const { primitives, randomBytesDrawn } = securePrimitives();
  const native = webcrypto;

  await withGlobalCrypto(native, async () => {
    assert.equal(installPkceCrypto(globalThis, primitives), false);
    assert.ok(globalThis.crypto === native, "the native object is untouched");

    const real = createRealClient();

    await real.signUp();
    assert.equal(real.requests[0].body.code_challenge_method, "s256");
    assert.equal(randomBytesDrawn(), 0, "the injected primitives were not used");
  });
});

test("H: a partial WebCrypto only gets the missing piece; the native getRandomValues is kept", async () => {
  const { primitives, randomBytesDrawn } = securePrimitives();
  let nativeCalls = 0;
  const partial = { getRandomValues: (array: Uint32Array) => { nativeCalls += 1; return webcrypto.getRandomValues(array); } };

  await withGlobalCrypto(partial, async () => {
    assert.equal(installPkceCrypto(globalThis, primitives), true);
    assert.ok(globalThis.crypto === (partial as unknown), "the existing object is completed in place");

    const real = createRealClient();

    await real.signUp();
    assert.equal(real.requests[0].body.code_challenge_method, "s256");
    assert.ok(nativeCalls > 0 && randomBytesDrawn() === 0, "native randomness kept, only subtle.digest added");
  });
});

test("wiring: the app installs the secure crypto before creating the client and guards its fetch; nothing falls back to Math.random", () => {
  const codeOnly = (file: string) =>
    readFileSync(new URL(file, import.meta.url), "utf8").split("\n").filter((line) => !line.trim().startsWith("//")).join("\n");
  const supabase = readFileSync(new URL("./supabase.ts", import.meta.url), "utf8");

  assert.ok(supabase.indexOf('import "./pkce-crypto-runtime"') !== -1, "supabase.ts installs the secure crypto");
  assert.ok(supabase.indexOf('import "./pkce-crypto-runtime"') < supabase.indexOf("createClient("), "before the first client exists");
  assert.ok(supabase.includes("guardAgainstPlainPkce("), "the fetch guard is wired in");
  assert.ok(!codeOnly("./pkce-crypto.ts").includes("Math.random"), "the shim never uses Math.random");
  assert.ok(!codeOnly("./pkce-crypto-runtime.ts").includes("Math.random"), "the native wiring never uses Math.random");
  assert.ok(!codeOnly("./pkce-crypto-runtime.ts").includes("getRandomBytes("), "expo-crypto's getRandomBytes has a dev Math.random fallback and is not used");
});
