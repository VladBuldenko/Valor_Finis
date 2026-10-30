import { Stack, useRouter, usePathname, type Href } from "expo-router";
import { useEffect } from "react";
import {
  ActivityIndicator,
  View,
} from "react-native";

import {
  AuthProvider,
  useAuth,
} from "../src/features/auth/auth-context";
import { navigationIntent } from "../src/features/auth/navigation-intent";
import { SessionScope } from "../src/lib/session-scope";
import { sessionQueryClient } from "../src/lib/session-runtime";

function RootNavigator() {
  const { session, isLoading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const userId = session?.user.id ?? null;

  // Remember the last in-app location while signed in, so a session the
  // server invalidates can return there after re-authentication.
  useEffect(() => {
    if (userId) {
      navigationIntent.track(userId, pathname);
    }
  }, [userId, pathname]);

  // After signing in, restore the saved location (same user only, once).
  useEffect(() => {
    if (!userId) {
      return;
    }

    const restored = navigationIntent.consumeFor(userId);

    if (restored) {
      router.replace(restored as Href);
    }
  }, [userId, router]);

  if (isLoading) {
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
      <Stack.Protected guard={!session}>
        <Stack.Screen name="sign-in" />
      </Stack.Protected>

      <Stack.Protected guard={!!session}>
        <Stack.Screen name="(app)" />
      </Stack.Protected>
    </Stack>
  );
}

export default function RootLayout() {
  // AuthProvider is stable; everything that reads server state lives in a
  // SessionScope that remounts when the signed-in user changes.
  return (
    <AuthProvider>
      <SessionScope holder={sessionQueryClient}>
        <RootNavigator />
      </SessionScope>
    </AuthProvider>
  );
}
