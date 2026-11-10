import { Link } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { Text, View } from "react-native";

import { AuthButton, AuthMessage, AuthScreen, authStyles } from "./auth-screen";
import { createSubmitGuard } from "./auth-registration";
import { resendConfirmationEmail } from "./auth.service";
import { pendingConfirmation } from "./pending-confirmation";
import { useIsMounted } from "./use-is-mounted";
import { useResendCooldown } from "./use-resend-cooldown";

// Shown after sign-up when no session exists yet. The wording is the same whether
// the address is new or already registered (copy rule C6) and never claims that
// an email was delivered.
export function CheckEmailScreen() {
  const isMounted = useIsMounted();
  const guard = useRef(createSubmitGuard()).current;
  const cooldown = useResendCooldown();
  const [email] = useState(() => pendingConfirmation.get());
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ tone: "info" | "error"; text: string } | null>(null);

  useEffect(() => () => pendingConfirmation.clear(), []);

  async function resend() {
    if (!email || !guard.tryStart()) {
      return;
    }

    setBusy(true);
    setNotice(null);

    try {
      const outcome = await resendConfirmationEmail(email, isMounted);

      if (outcome.kind === "stale" || !isMounted()) {
        return;
      }

      if (outcome.kind === "sent") {
        cooldown.start();
        setNotice({ tone: "info", text: "If a message is needed, it is on its way. Check your inbox and spam folder." });
      } else {
        setNotice({ tone: "error", text: outcome.message });
      }
    } finally {
      guard.end();

      if (isMounted()) {
        setBusy(false);
      }
    }
  }

  return (
    <AuthScreen title="Check your email">
      <Text>
        {email
          ? `We sent instructions to ${email}. Open the link in the message to finish, then sign in.`
          : "We sent instructions to the address you entered. Open the link in the message to finish, then sign in."}
      </Text>
      <Text>The message can take a few minutes. Check your spam folder too.</Text>
      {notice ? <AuthMessage tone={notice.tone}>{notice.text}</AuthMessage> : null}
      {email ? (
        <AuthButton
          label={cooldown.secondsLeft > 0 ? `Send again in ${cooldown.secondsLeft}s` : "Send the email again"}
          busy={busy}
          disabled={cooldown.secondsLeft > 0}
          onPress={resend}
        />
      ) : null}
      <View style={authStyles.linkRow}>
        <Link href="/sign-in" replace accessibilityRole="link">
          <Text style={authStyles.linkText}>Back to sign in</Text>
        </Link>
      </View>
    </AuthScreen>
  );
}
