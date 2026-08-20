import { useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  SafeAreaView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { signOut } from "../../src/features/auth/auth.service";

export default function DashboardScreen() {
  const [isSigningOut, setIsSigningOut] = useState(false);

  async function handleSignOut() {
    try {
      setIsSigningOut(true);

      await signOut();
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Unable to sign out.";

      Alert.alert("Sign out failed", message);
    } finally {
      setIsSigningOut(false);
    }
  }

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.content}>
        <Text style={styles.title}>
          Valor Finis
        </Text>

        <Text style={styles.subtitle}>
          Dashboard
        </Text>

        <Pressable
          disabled={isSigningOut}
          onPress={handleSignOut}
          style={styles.button}
        >
          {isSigningOut ? (
            <ActivityIndicator />
          ) : (
            <Text style={styles.buttonText}>
              Log out
            </Text>
          )}
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  content: {
    flex: 1,
    paddingHorizontal: 24,
    paddingTop: 32,
  },
  title: {
    fontSize: 32,
    fontWeight: "700",
  },
  subtitle: {
    fontSize: 20,
    marginTop: 8,
  },
  button: {
    alignItems: "center",
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 14,
    marginTop: 32,
  },
  buttonText: {
    fontSize: 16,
    fontWeight: "600",
  },
});