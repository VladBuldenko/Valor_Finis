import type { ReactNode } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type TextInputProps,
} from "react-native";

// The shared frame and controls of the authentication screens (sign-up, check
// email, forgot password, reset password). Same look as the sign-in screen: plain
// bordered inputs and a bordered button, no new visual language.

export function AuthScreen(props: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <SafeAreaView style={styles.container}>
      <KeyboardAvoidingView style={styles.container} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <Text accessibilityRole="header" style={styles.title}>
            {props.title}
          </Text>
          {props.subtitle ? <Text style={styles.subtitle}>{props.subtitle}</Text> : null}
          {props.children}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

export function AuthField(props: TextInputProps & { label: string; error?: string | undefined }) {
  const { label, error, style, ...input } = props;

  return (
    <View style={styles.field}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        autoCapitalize="none"
        autoCorrect={false}
        style={[styles.input, error ? styles.inputError : null, style]}
        {...input}
      />
      {error ? (
        <Text accessibilityLiveRegion="polite" style={styles.fieldError}>
          {error}
        </Text>
      ) : null}
    </View>
  );
}

export function AuthButton(props: { label: string; onPress: () => void; busy?: boolean; disabled?: boolean; quiet?: boolean }) {
  const inactive = props.busy === true || props.disabled === true;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={props.label}
      accessibilityState={{ disabled: inactive, busy: props.busy === true }}
      disabled={inactive}
      onPress={props.onPress}
      style={[styles.button, props.quiet ? styles.quietButton : null, inactive ? styles.inactive : null]}
    >
      {props.busy ? <ActivityIndicator /> : <Text style={styles.buttonText}>{props.label}</Text>}
    </Pressable>
  );
}

// A message that must be announced: a failure or a result.
export function AuthMessage(props: { children: ReactNode; tone?: "error" | "info" }) {
  return (
    <View
      accessibilityLiveRegion="polite"
      accessibilityRole={props.tone === "error" ? "alert" : undefined}
      style={[styles.message, props.tone === "error" ? styles.messageError : null]}
    >
      <Text style={styles.messageText}>{props.children}</Text>
    </View>
  );
}

export const authStyles = StyleSheet.create({
  linkRow: { alignItems: "center", paddingVertical: 8 },
  linkText: { fontSize: 16, textDecorationLine: "underline" },
});

const styles = StyleSheet.create({
  container: { flex: 1 },
  content: { flexGrow: 1, justifyContent: "center", paddingHorizontal: 24, paddingVertical: 24, gap: 16 },
  title: { fontSize: 32, fontWeight: "700" },
  subtitle: { fontSize: 18, marginBottom: 8 },
  field: { gap: 6 },
  label: { fontSize: 14, fontWeight: "600" },
  input: { borderWidth: 1, borderRadius: 10, paddingHorizontal: 16, paddingVertical: 14, fontSize: 16 },
  inputError: { borderWidth: 2 },
  fieldError: { fontSize: 14 },
  button: { alignItems: "center", borderWidth: 1, borderRadius: 10, paddingVertical: 14, marginTop: 8, minHeight: 48 },
  quietButton: { borderWidth: 0 },
  inactive: { opacity: 0.5 },
  buttonText: { fontSize: 16, fontWeight: "600" },
  message: { borderWidth: 1, borderRadius: 10, padding: 14 },
  messageError: { borderWidth: 2 },
  messageText: { fontSize: 15 },
});
