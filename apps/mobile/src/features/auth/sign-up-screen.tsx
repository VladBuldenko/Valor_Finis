import { Link, useRouter } from "expo-router";
import { useRef, useState } from "react";
import { Text, View } from "react-native";

import { AuthButton, AuthField, AuthMessage, AuthScreen, authStyles } from "./auth-screen";
import { createSubmitGuard, validateSignUpForm, type SignUpFieldErrors } from "./auth-registration";
import { signUpWithEmail } from "./auth.service";
import { pendingConfirmation } from "./pending-confirmation";
import { useIsMounted } from "./use-is-mounted";

export function SignUpScreen() {
  const router = useRouter();
  const isMounted = useIsMounted();
  const guard = useRef(createSubmitGuard()).current;
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<SignUpFieldErrors>({});
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    // Synchronous: two quick taps cannot both start a request.
    if (!guard.tryStart()) {
      return;
    }

    const found = validateSignUpForm({ email, password, confirm });

    setErrors(found);
    setFailure(null);

    if (Object.keys(found).length > 0) {
      guard.end();

      return;
    }

    setBusy(true);

    try {
      const outcome = await signUpWithEmail(email, password, isMounted);

      if (outcome.kind === "stale" || !isMounted()) {
        return;
      }

      switch (outcome.kind) {
        case "check_email":
          pendingConfirmation.set(outcome.email);
          router.replace("/check-email");
          break;
        case "rejected":
          setErrors({ [outcome.field]: outcome.message });
          break;
        case "failed":
          setFailure(outcome.message);
          break;
        default:
          // signed_in: the auth provider adopts the session and the navigator moves on.
          break;
      }
    } finally {
      guard.end();

      if (isMounted()) {
        setBusy(false);
      }
    }
  }

  return (
    <AuthScreen title="Create account" subtitle="Start with your email and a password">
      <AuthField
        label="Email"
        autoComplete="email"
        keyboardType="email-address"
        textContentType="emailAddress"
        value={email}
        onChangeText={setEmail}
        error={errors.email}
        editable={!busy}
      />
      <AuthField
        label="Password"
        autoComplete="new-password"
        textContentType="newPassword"
        secureTextEntry
        value={password}
        onChangeText={setPassword}
        error={errors.password}
        editable={!busy}
      />
      <AuthField
        label="Confirm password"
        autoComplete="new-password"
        textContentType="newPassword"
        secureTextEntry
        value={confirm}
        onChangeText={setConfirm}
        error={errors.confirm}
        editable={!busy}
        onSubmitEditing={submit}
      />
      {failure ? <AuthMessage tone="error">{failure}</AuthMessage> : null}
      <AuthButton label="Create account" busy={busy} onPress={submit} />
      <View style={authStyles.linkRow}>
        <Link href="/sign-in" replace accessibilityRole="link">
          <Text style={authStyles.linkText}>I already have an account</Text>
        </Link>
      </View>
    </AuthScreen>
  );
}
