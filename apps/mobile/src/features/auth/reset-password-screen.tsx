import { useRef, useState } from "react";
import { Alert } from "react-native";

import { AuthButton, AuthField, AuthMessage, AuthScreen } from "./auth-screen";
import { createSubmitGuard, validateResetForm, type ResetFieldErrors } from "./auth-registration";
import { cancelRecovery, setRecoveredPassword } from "./auth.service";
import { signedOutLanding, type SignedOutLanding } from "./pending-confirmation";
import { useIsMounted } from "./use-is-mounted";

// Reached only while a password recovery is active (the root navigator guards it).
// The recovery session is not an app session: the data screens stay unmounted
// until the password is changed.
export function ResetPasswordScreen() {
  const isMounted = useIsMounted();
  const guard = useRef(createSubmitGuard()).current;
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<ResetFieldErrors>({});
  const [failure, setFailure] = useState<string | null>(null);
  const [expired, setExpired] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!guard.tryStart()) {
      return;
    }

    const found = validateResetForm({ password, confirm });

    setErrors(found);
    setFailure(null);

    if (Object.keys(found).length > 0) {
      guard.end();

      return;
    }

    setBusy(true);

    try {
      const outcome = await setRecoveredPassword(password, isMounted);

      if (outcome.kind === "stale" || !isMounted()) {
        return;
      }

      switch (outcome.kind) {
        case "updated":
          // The navigator now moves to the app; say so once.
          Alert.alert("Password updated", "Your password was changed. You are signed in.");
          break;
        case "rejected":
          setErrors({ password: outcome.message });
          break;
        case "session_expired":
          setExpired(true);
          break;
        default:
          setFailure(outcome.message);
          break;
      }
    } finally {
      guard.end();

      if (isMounted()) {
        setBusy(false);
      }
    }
  }

  async function leave(next: SignedOutLanding) {
    if (!guard.tryStart()) {
      return;
    }

    setBusy(true);

    try {
      // The target waits until the session has ended; the root navigator applies it.
      signedOutLanding.set(next);

      // Ends the recovery session on this device only.
      const result = await cancelRecovery();

      if (result !== "cancelled") {
        signedOutLanding.clear();
      }

      if (result === "failed" && isMounted()) {
        setFailure("We could not leave the reset. Check your connection and try again.");
      }
    } finally {
      guard.end();

      if (isMounted()) {
        setBusy(false);
      }
    }
  }

  return (
    <AuthScreen title="Choose a new password">
      {expired ? (
        <>
          <AuthMessage tone="error">
            This reset session has expired. Request a new link to try again.
          </AuthMessage>
          {failure ? <AuthMessage tone="error">{failure}</AuthMessage> : null}
          <AuthButton label="Request a new link" busy={busy} onPress={() => leave("/forgot-password")} />
        </>
      ) : (
        <>
          <AuthField
            label="New password"
            autoComplete="new-password"
            textContentType="newPassword"
            secureTextEntry
            value={password}
            onChangeText={setPassword}
            error={errors.password}
            editable={!busy}
          />
          <AuthField
            label="Confirm new password"
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
          <AuthButton label="Save new password" busy={busy} onPress={submit} />
          <AuthButton label="Cancel" quiet disabled={busy} onPress={() => leave("/sign-in")} />
        </>
      )}
    </AuthScreen>
  );
}
