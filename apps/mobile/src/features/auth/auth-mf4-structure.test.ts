// MF-4 structural guards: what the sign-up / recovery code must never do, checked
// against the source (the screens cannot be mounted by the Node runner).
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { stripComments } from "../financial-rules/financial-rule-forbidden-copy.ts";
import { createNavigationIntentStore, sanitizeReturnPath } from "./navigation-intent.ts";

const code = (path: string) => stripComments(readFileSync(path, "utf8"));

const LOGIC = [
  "src/features/auth/auth-link.ts",
  "src/features/auth/auth-link-handler.ts",
  "src/features/auth/auth-errors.ts",
  "src/features/auth/auth-registration.ts",
  "src/features/auth/password-recovery.ts",
  "src/features/auth/recovery-state.ts",
  "src/features/auth/native-intent.ts",
];
const SCREENS = [
  "src/features/auth/sign-up-screen.tsx",
  "src/features/auth/check-email-screen.tsx",
  "src/features/auth/forgot-password-screen.tsx",
  "src/features/auth/reset-password-screen.tsx",
];
const WIRING = [
  "src/features/auth/auth.service.ts",
  "src/features/auth/auth-link-host.tsx",
  "src/lib/auth-link-runtime.ts",
  "app/+native-intent.ts",
  "app/sign-up.tsx",
  "app/check-email.tsx",
  "app/forgot-password.tsx",
  "app/reset-password.tsx",
];
const ALL = [...LOGIC, ...SCREENS, ...WIRING];

describe("no secret can reach a log or a screen", () => {
  it("none of the new code logs anything", () => {
    for (const path of ALL) {
      assert.doesNotMatch(code(path), /\bconsole\s*\./, path);
    }
  });

  it("no raw error text is ever shown or returned: messages come from the failure class", () => {
    for (const path of ALL) {
      assert.doesNotMatch(code(path), /\b(error|err|e|cause|response\.error|result\.error)\.message\b/, path);
    }
  });

  it("the credential of a link never becomes a route, a route parameter or a stored value", () => {
    for (const path of [...SCREENS, "src/features/auth/auth-link-host.tsx", "app/+native-intent.ts"]) {
      const source = code(path);

      assert.doesNotMatch(source, /useLocalSearchParams|useGlobalSearchParams|Linking\.|AsyncStorage|localStorage/, path);
    }
  });

  it("no passwords or tokens are written into Alert text", () => {
    for (const path of [...SCREENS, "src/features/auth/auth-link-host.tsx"]) {
      for (const match of code(path).matchAll(/Alert\.alert\(([^;]*?)\);/gs)) {
        assert.doesNotMatch(match[1], /password(?!\s+(was|updated))|token|session\./i, `${path}: ${match[1].slice(0, 80)}`);
      }
    }
  });
});

describe("layering", () => {
  it("screens never talk to Supabase; only the service and the runtime do", () => {
    for (const path of [...SCREENS, "src/features/auth/auth-link-host.tsx"]) {
      assert.doesNotMatch(code(path), /lib\/supabase|@supabase\/supabase-js|rawSupabase/, path);
    }
  });

  it("the pure logic imports no React Native, Expo or Supabase module", () => {
    for (const path of LOGIC) {
      assert.doesNotMatch(code(path), /from "(react-native|expo[^"]*|@supabase[^"]*|react)"/, path);
    }
  });

  it("nothing retries an authentication call by itself", () => {
    for (const path of [...LOGIC, ...SCREENS, "src/features/auth/auth.service.ts"]) {
      assert.doesNotMatch(code(path), /\bretry\b|setTimeout\(|while\s*\(true\)/i, path);
    }
  });

  it("the guarded gateway still lists signUp, setSession, exchangeCodeForSession and verifyOtp as queued", () => {
    const gateway = readFileSync("src/api/auth-gateway.ts", "utf8");

    for (const method of ["signUp", "setSession", "exchangeCodeForSession", "verifyOtp", "signOut"]) {
      assert.match(gateway.slice(0, gateway.indexOf("SESSION_PASSTHROUGH")), new RegExp(`"${method}"`), method);
    }
  });

  it("the link runtime uses the guarded client, never the raw one", () => {
    assert.doesNotMatch(code("src/lib/auth-link-runtime.ts"), /rawSupabase/);
    assert.match(code("src/lib/auth-link-runtime.ts"), /supabase\.auth\.exchangeCodeForSession/);
  });

  it("login CSRF: the client uses PKCE and no link can carry a session or token hash into the app", () => {
    assert.match(code("src/lib/supabase.ts"), /flowType:\s*"pkce"/);

    for (const path of ["src/lib/auth-link-runtime.ts", "src/features/auth/auth-link-handler.ts"]) {
      assert.doesNotMatch(code(path), /setSession|verifyOtp|setSession\(/, path);
    }
  });
});

describe("routes and the protected-route guard", () => {
  const layout = code("app/_layout.tsx");

  it("every new screen has a route file and is registered in a guard group", () => {
    for (const route of ["sign-up", "check-email", "forgot-password", "reset-password"]) {
      assert.ok(existsSync(`app/${route}.tsx`), route);
      assert.match(layout, new RegExp(`<Stack\\.Screen name="${route}"`), route);
    }
  });

  it("signed-out screens, the recovery screen and the app are separate guard groups", () => {
    const groups = [...layout.matchAll(/<Stack\.Protected guard=\{([^}]+)\}>([\s\S]*?)<\/Stack\.Protected>/g)].map((m) => ({ guard: m[1].trim(), body: m[2] }));
    const by = (guard: string) => groups.find((group) => group.guard === guard)?.body ?? "";

    assert.match(by('route === "signed-out"'), /name="sign-in"[\s\S]*name="sign-up"[\s\S]*name="check-email"[\s\S]*name="forgot-password"/);
    assert.match(by('route === "recovery"'), /name="reset-password"/);
    assert.match(by('route === "app"'), /name="\(app\)"/);
    assert.equal(groups.length, 3);
  });

  it("the saved location is restored only in the app route, never while recovering", () => {
    const effect = layout.slice(layout.indexOf("consumeFor") - 300, layout.indexOf("consumeFor") + 200);

    assert.match(effect, /route !== "app"/);
    assert.match(layout, /route === "app"[\s\S]{0,80}navigationIntent\.track|navigationIntent\.track\(userId, pathname\)/);
  });

  it("the auth link host is inside the auth provider, and the rules host follows the app route", () => {
    assert.match(layout, /<AuthProvider>[\s\S]*<AuthLinkHost \/>[\s\S]*<RootNavigator \/>/);
    assert.match(code("src/features/financial-rules/rules-evaluation-host.tsx"), /useAppUserId\(\)/);
  });

  it("sign-in keeps its behavior and gains links to the new screens", () => {
    const signIn = code("app/sign-in.tsx");

    assert.match(signIn, /signInWithEmail\(/);
    assert.match(signIn, /href="\/forgot-password"/);
    assert.match(signIn, /href="\/sign-up"/);
  });
});

describe("restored navigation intent and the new screens", () => {
  it("a signed-out screen is never a place to return to", () => {
    for (const path of ["/sign-in", "/sign-up", "/check-email", "/forgot-password", "/reset-password", "/auth/callback", "/sign-up/x"]) {
      assert.equal(sanitizeReturnPath(path), null, path);
    }

    assert.equal(sanitizeReturnPath("/goals/new"), "/goals/new");
    assert.equal(sanitizeReturnPath("/rules/abc"), "/rules/abc");
  });

  it("an intent saved by a server-ended session is restored for the same user only, once", () => {
    const store = createNavigationIntentStore(() => 1_000);

    store.track("user-a", "/goals/new");
    store.captureOnInvalidation();
    assert.equal(store.consumeFor("user-b"), null, "another user (also by a recovery) never gets it");
    assert.equal(store.consumeFor("user-a"), null, "and a different user's attempt erased it");

    store.track("user-a", "/goals/new");
    store.captureOnInvalidation();
    assert.equal(store.consumeFor("user-a"), "/goals/new");
    assert.equal(store.consumeFor("user-a"), null);
  });

  it("cancelling a recovery discards any saved location", () => {
    const service = code("src/features/auth/auth.service.ts");
    const cancel = service.slice(service.indexOf("export async function cancelRecovery"));

    assert.match(cancel, /navigationIntent\.discard\(\)/);
  });
});
