import { useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  SafeAreaView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { signInWithEmail } from "../src/features/auth/auth.service";
import { getCategories } from "../src/features/categories/category.service";

export default function LoginScreen() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isBackendLoading, setIsBackendLoading] = useState(false);

  async function handleLogin() {
    if (!email.trim() || !password) {
      Alert.alert(
        "Missing data",
        "Enter your email and password.",
      );
      return;
    }

    try {
      setIsLoading(true);

      const session = await signInWithEmail(
        email,
        password,
      );

      if (!session) {
        Alert.alert(
          "Login failed",
          "Supabase did not return a session.",
        );
        return;
      }

      Alert.alert(
        "Success",
        "You are signed in.",
      );
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Unable to sign in.";

      Alert.alert("Login failed", message);
    } finally {
      setIsLoading(false);
    }
  }

  async function handleBackendTest() {
    try {
      setIsBackendLoading(true);

      const categories = await getCategories();

      Alert.alert(
        "Backend connected",
        `Categories received: ${categories.length}`,
      );
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Unable to connect to backend.";

      Alert.alert(
        "Backend error",
        message,
      );
    } finally {
      setIsBackendLoading(false);
    }
  }

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.content}>
        <Text style={styles.title}>
          Valor Finis
        </Text>

        <Text style={styles.subtitle}>
          Sign in to your account
        </Text>

        <TextInput
          autoCapitalize="none"
          autoComplete="email"
          keyboardType="email-address"
          placeholder="Email"
          value={email}
          onChangeText={setEmail}
          style={styles.input}
        />

        <TextInput
          autoCapitalize="none"
          autoComplete="password"
          placeholder="Password"
          secureTextEntry
          value={password}
          onChangeText={setPassword}
          style={styles.input}
        />

        <Pressable
          disabled={isLoading}
          onPress={handleLogin}
          style={styles.button}
        >
          {isLoading ? (
            <ActivityIndicator />
          ) : (
            <Text style={styles.buttonText}>
              Sign in
            </Text>
          )}
        </Pressable>

        <Pressable
          disabled={isBackendLoading}
          onPress={handleBackendTest}
          style={styles.button}
        >
          {isBackendLoading ? (
            <ActivityIndicator />
          ) : (
            <Text style={styles.buttonText}>
              Test Backend
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
    justifyContent: "center",
    paddingHorizontal: 24,
    gap: 16,
  },
  title: {
    fontSize: 36,
    fontWeight: "700",
  },
  subtitle: {
    fontSize: 18,
    marginBottom: 16,
  },
  input: {
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 16,
    paddingVertical: 14,
    fontSize: 16,
  },
  button: {
    alignItems: "center",
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 14,
    marginTop: 8,
  },
  buttonText: {
    fontSize: 16,
    fontWeight: "600",
  },
});