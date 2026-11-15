// Secure PKCE for Supabase Auth on React Native (MOBILE-002A).
//
// Why this exists. @supabase/auth-js (2.112.x) reads the GLOBAL `crypto` and has no way to inject one. Hermes
// (Expo Go 57 / RN 0.86) defines no `crypto` at all, so without this module auth-js:
//  * draws the PKCE verifier and the flow id from Math.random (it silently falls back when `crypto` is undefined);
//  * finds no `crypto.subtle`, returns the verifier itself as the challenge and sends code_challenge_method=plain
//    (the "WebCrypto API is not supported ... plain instead of sha256" warning).
// expo-crypto does not define a global either: it only exports functions. This module wires exactly the two
// functions auth-js needs (getRandomValues, subtle.digest for SHA-256) from injected secure primitives.
//
// Rules: nothing here ever falls back. If a secure primitive is unavailable or misbehaves the call throws and auth-js
// aborts the request before anything is sent; a request that would still carry the plain method is refused by
// guardAgainstPlainPkce. An existing native WebCrypto (web, or a future Hermes) is left untouched.
// Pure and Node-testable: the native expo-crypto functions are injected by pkce-crypto-runtime.ts.

export class PkceCryptoUnavailableError extends Error {
  constructor(message: string) {
    super(`Secure PKCE is unavailable: ${message}`);
    this.name = "PkceCryptoUnavailableError";
  }
}

export type SecureCryptoPrimitives = {
  getRandomValues: <T extends ArrayBufferView>(array: T) => T;
  digestSha256: (data: BufferSource) => Promise<ArrayBuffer>;
};

type CryptoLike = { getRandomValues?: unknown; subtle?: { digest?: unknown } };

const SHA256_BYTES = 32;
// WebCrypto's per-call limit for getRandomValues.
const MAX_RANDOM_BYTES = 65_536;

function isIntegerTypedArray(value: unknown): value is ArrayBufferView {
  return (
    ArrayBuffer.isView(value) &&
    !(value instanceof DataView) &&
    !(value instanceof Float32Array) &&
    !(value instanceof Float64Array)
  );
}

function define(target: object, name: string, value: unknown): void {
  Object.defineProperty(target, name, { value, configurable: true, enumerable: true, writable: true });
}

// Installs only the missing WebCrypto pieces on `target.crypto`. Returns false when a complete native WebCrypto
// (getRandomValues and subtle.digest) is already present and nothing was changed.
export function installPkceCrypto(target: { crypto?: unknown }, primitives: SecureCryptoPrimitives): boolean {
  const existing = target.crypto as CryptoLike | null | undefined;
  const needsRandom = typeof existing?.getRandomValues !== "function";
  const needsDigest = typeof existing?.subtle?.digest !== "function";

  if (!needsRandom && !needsDigest) {
    return false;
  }

  const base: object = existing !== null && typeof existing === "object" ? existing : {};

  if (needsRandom) {
    define(
      base,
      "getRandomValues",
      <T extends ArrayBufferView>(array: T): T => {
        if (!isIntegerTypedArray(array)) {
          throw new TypeError("getRandomValues expects an integer typed array");
        }

        if (array.byteLength > MAX_RANDOM_BYTES) {
          throw new RangeError("getRandomValues: requested more than 65536 bytes");
        }

        return primitives.getRandomValues(array);
      },
    );
  }

  if (needsDigest) {
    define(
      base,
      "subtle",
      {
        digest: async (algorithm: unknown, data: BufferSource): Promise<ArrayBuffer> => {
          const name = typeof algorithm === "string" ? algorithm : (algorithm as { name?: unknown } | null)?.name;

          if (typeof name !== "string" || name.toUpperCase() !== "SHA-256") {
            throw new PkceCryptoUnavailableError("only SHA-256 is provided");
          }

          const digest = await primitives.digestSha256(data);

          if (!(digest instanceof ArrayBuffer) || digest.byteLength !== SHA256_BYTES) {
            throw new PkceCryptoUnavailableError("the SHA-256 primitive returned an invalid digest");
          }

          return digest;
        },
      },
    );
  }

  if (base !== existing) {
    define(target, "crypto", base);
  }

  return true;
}

const PLAIN_METHOD_IN_BODY = /"code_challenge_method"\s*:\s*"plain"/i;
const PLAIN_METHOD_IN_URL = /[?&]code_challenge_method=plain(?:&|#|$)/i;

// Last line of defence at the network layer: whatever auth-js does in some future runtime, a request that asks the
// server to accept the plain code-challenge method is never sent.
export function guardAgainstPlainPkce(baseFetch: typeof fetch): typeof fetch {
  return (input, init) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const plain =
      PLAIN_METHOD_IN_URL.test(url) || (typeof init?.body === "string" && PLAIN_METHOD_IN_BODY.test(init.body));

    if (plain) {
      return Promise.reject(new PkceCryptoUnavailableError("refusing a request that uses the plain code challenge"));
    }

    return baseFetch(input, init);
  };
}
