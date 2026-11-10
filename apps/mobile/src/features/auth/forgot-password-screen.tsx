import { Link } from "expo-router";
import { useRef, useState } from "react";
import { Text, View } from "react-native";

import { AuthButton, AuthField, AuthMessage, AuthScreen, authStyles } from "./auth-screen";
import { createSubmitGuard, validateEmail } from "./auth-registration";
import { sendPasswordResetEmail } from "./auth.service";
import { useIsMounted } from "./use-is-mounted";
import { useResendCooldown } from "./use-resend-cooldown";

// The request step of password recovery. The same confirmation is shown for every
// address, known or not (copy rule C6), and it never claims delivery.
export function ForgotPasswordScreen() {
  const isMounted = useIsMounted();
  const guard = useRef(createSubmitGuard()).current;
  const cooldown = useResendCooldown();
  const [email, setEmail] = useState("");
  const [fieldError, setFieldError] = useState<string | undefined>(undefined);
  const [failure, setFailure] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!guard.tryStart()) {
      return;
    }

    const problem = validateEmail(email);

    setFieldError(problem ?? undefined);
    setFailure(null);

    if (problem) {
      guard.end();

      return;
    }

    setBusy(true);

    try {
      const outcome = await sendPasswordResetEmail(email, isMounted);

      if (outcome.kind === "stale" || !isMounted()) {
        return;
      }

      if (outcome.kind === "sent") {
        setSentTo(outcome.email);
        cooldown.start();
      } else if (outcome.kind === "rejected") {
        setFieldError(outcome.message);
      } else {
        setFailure(outcome.message);
      }
    } finally {
      guard.end();

      if (isMounted()) {
        setBusy(false);
      }
    }
  }

  return (
    <AuthScreen title="Reset password" subtitle="We will email you a link to choose a new password">
      <AuthField
        label="Email"
        autoComplete="email"
        keyboardType="email-address"
        textContentType="emailAddress"
        value={email}
        onChangeText={setEmail}
        error={fieldError}
        editable={!busy}
        onSubmitEditing={submit}
      />
      {sentTo ? (
        <AuthMessage tone="info">
          {`If an account can use ${sentTo}, we sent a link to reset the password. Open it on this device. It can take a few minutes.`}
        </AuthMessage>
      ) : null}
      {failure ? <AuthMessage tone="error">{failure}</AuthMessage> : null}
      <AuthButton
        label={sentTo ? (cooldown.secondsLeft > 0 ? `Send again in ${cooldown.secondsLeft}s` : "Send the link again") : "Send reset link"}
        busy={busy}
        disabled={cooldown.secondsLeft > 0}
        onPress={submit}
      />
      <View style={authStyles.linkRow}>
        <Link href="/sign-in" replace accessibilityRole="link">
          <Text style={authStyles.linkText}>Back to sign in</Text>
        </Link>
      </View>
    </AuthScreen>
  );
}
