// Test support for the PKCE tests: the REAL installed @supabase/supabase-js running against a fake network
// and an in-memory storage, inside a chosen `globalThis.crypto`. Nothing here is a copy of the library's PKCE logic.
// Never log or assert-print a verifier, code or token: assertions below compare booleans and lengths only.
import { createHash } from "node:crypto";
import { createClient } from "@supabase/supabase-js";

export type RecordedRequest = { url: string; body: Record<string, unknown> };

export function memoryStorage() {
  const items = new Map<string, string>();

  return {
    items,
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => void items.set(key, value),
    removeItem: (key: string) => void items.delete(key),
  };
}

// Runs `run` with `globalThis.crypto` replaced (`undefined` = what Hermes in Expo Go 57 really has), then restores it.
export async function withGlobalCrypto<T>(replacement: unknown, run: () => Promise<T>): Promise<T> {
  const original = Object.getOwnPropertyDescriptor(globalThis, "crypto");

  Object.defineProperty(globalThis, "crypto", { value: replacement, configurable: true, writable: true });

  try {
    return await run();
  } finally {
    if (original) {
      Object.defineProperty(globalThis, "crypto", original);
    } else {
      delete (globalThis as { crypto?: unknown }).crypto;
    }
  }
}

// Counts Math.random calls made while `run` executes (the library's silent fallback when `crypto` is undefined).
export async function countMathRandomCalls<T>(run: () => Promise<T>): Promise<{ result: T; calls: number }> {
  const original = Math.random;
  let calls = 0;

  Math.random = () => {
    calls += 1;
    return original();
  };

  try {
    return { result: await run(), calls };
  } finally {
    Math.random = original;
  }
}

export function sha256Base64Url(value: string): string {
  return createHash("sha256").update(value).digest("base64url");
}

// A real client (PKCE, like src/lib/supabase.ts) whose only fakes are the network and the storage.
export function createRealClient(wrapFetch: (inner: typeof fetch) => typeof fetch = (inner) => inner) {
  const storage = memoryStorage();
  const requests: RecordedRequest[] = [];
  const fakeNetwork: typeof fetch = async (input, init) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const body = typeof init?.body === "string" ? (JSON.parse(init.body) as Record<string, unknown>) : {};

    requests.push({ url, body });

    return new Response(
      JSON.stringify({ id: "00000000-0000-4000-8000-000000000001", aud: "authenticated", email: "fake@example.test" }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  };
  const client = createClient("http://127.0.0.1:54321", "fake-publishable-key", {
    auth: {
      storage,
      flowType: "pkce",
      persistSession: true,
      autoRefreshToken: false,
      detectSessionInUrl: false,
    },
    global: { fetch: wrapFetch(fakeNetwork) },
  });

  // The verifier the library stored for the flow it just started (JSON-encoded string under the legacy mirror key).
  function storedVerifier(): string | null {
    const key = [...storage.items.keys()].find((name) => name.endsWith("-auth-token-code-verifier"));
    const raw = key === undefined ? undefined : storage.items.get(key);

    return raw === undefined ? null : (JSON.parse(raw) as string);
  }

  return { client, requests, storedVerifier, signUp: () => client.auth.signUp({ email: "fake@example.test", password: "fake-password-1" }) };
}
