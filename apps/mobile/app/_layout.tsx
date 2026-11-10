import { Stack, useRouter, usePathname, type Href } from "expo-router";
import { useEffect } from "react";
import {
  ActivityIndicator,
  View,
} from "react-native";

import {
  AuthProvider,
  useRootRoute,
} from "../src/features/auth/auth-context";
import { AuthLinkHost } from "../src/features/auth/auth-link-host";
import { signedOutLanding } from "../src/features/auth/pending-confirmation";
import { RulesEvaluationHost } from "../src/features/financial-rules/rules-evaluation-host";
import { navigationIntent } from "../src/features/auth/navigation-intent";
import { installAppFocusRuntime } from "../src/lib/app-focus-runtime";
import { SessionScope } from "../src/lib/session-scope";
import { sessionQueryClient } from "../src/lib/session-runtime";

function RootNavigator() {
  const { route, userId } = useRootRoute();
  const router = useRouter();
  const pathname = usePathname();

  // Remember the last in-app location while signed in, so a session the
  // server invalidates can return there after re-authentication.
  useEffect(() => {
    if (userId && route === "app") {
      navigationIntent.track(userId, pathname);
    }
  }, [userId, route, pathname]);

  // After signing in, restore the saved location (same user only, once).
  // Not while a password recovery is in progress: the recovery session is not an app
  // session, and the intent is restored (same user only, once) after it ends.
  useEffect(() => {
    if (!userId || route !== "app") {
      return;
    }

    const restored = navigationIntent.consumeFor(userId);

    if (restored) {
      router.replace(restored as Href);
    }
  }, [userId, route, router]);

  // A flow that ended the session on purpose (leaving a password recovery) may
  // name where the signed-out user should land.
  useEffect(() => {
    if (route !== "signed-out") {
      return;
    }

    const landing = signedOutLanding.consume();

    if (landing) {
      router.replace(landing);
    }
  }, [route, router]);

  if (route === "loading") {
    return (
      <View
        style={{
          flex: 1,
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <ActivityIndicator size="large" />
      </View>
    );
  }

  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Protected guard={route === "signed-out"}>
        <Stack.Screen name="sign-in" />
        <Stack.Screen name="sign-up" />
        <Stack.Screen name="check-email" />
        <Stack.Screen name="forgot-password" />
      </Stack.Protected>

      <Stack.Protected guard={route === "recovery"}>
        <Stack.Screen name="reset-password" />
      </Stack.Protected>

      <Stack.Protected guard={route === "app"}>
        <Stack.Screen name="(app)" />
      </Stack.Protected>
    </Stack>
  );
}

export default function RootLayout() {
  // The one place app foreground reaches TanStack Query's focus manager.
  useEffect(() => installAppFocusRuntime(), []);

  // AuthProvider is stable; everything that reads server state lives in a
  // SessionScope that remounts when the signed-in user changes.
  return (
    <AuthProvider>
      <SessionScope holder={sessionQueryClient}>
        <RulesEvaluationHost>
          <AuthLinkHost />
          <RootNavigator />
        </RulesEvaluationHost>
      </SessionScope>
    </AuthProvider>
  );
}
