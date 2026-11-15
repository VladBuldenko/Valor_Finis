// Wires the native expo-crypto primitives into the global `crypto` that Supabase Auth reads for PKCE.
// Import this BEFORE anything that creates a Supabase client (see supabase.ts). On iOS getRandomValues is
// SecRandomCopyBytes and digest is the platform SHA-256; there is deliberately no Math.random or JS fallback.
import { CryptoDigestAlgorithm, digest, getRandomValues } from "expo-crypto";

import { installPkceCrypto } from "./pkce-crypto";

installPkceCrypto(globalThis, {
  getRandomValues: (array) => {
    getRandomValues(array as unknown as Parameters<typeof getRandomValues>[0]); // fills `array` in place
    return array;
  },
  digestSha256: (data) => digest(CryptoDigestAlgorithm.SHA256, data),
});
