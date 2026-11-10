import { useRouter } from "expo-router";
import { useEffect, useSyncExternalStore } from "react";
import { Alert } from "react-native";

import { authLinkHandler } from "../../lib/auth-link-runtime";
import { useAuth, useRecoverySnapshot } from "./auth-context";
import type { LinkOutcome } from "./auth-link-handler";

// Mounted once, inside the AuthProvider. It (1) starts the pending auth link once
// authentication has been initialized, and whenever a new link arrives while the
// app runs, and (2) tells the user the result of a link that did not produce a
// usable session. The credential in the link never reaches this component: it is
// consumed by the handler (see app/+native-intent.ts).
const INVALID_LINK_TITLE = "Link not valid";
const INVALID_LINK_TEXT =
  "This link is invalid, has expired, was already used, or was not requested on this device. If you were resetting your password, request a new link here. If you were confirming your email, try signing in.";

function showNotice(outcome: LinkOutcome, signedIn: boolean, requestNewLink: () => void): void {
  switch (outcome.kind) {
    case "link_invalid":
      Alert.alert(
        INVALID_LINK_TITLE,
        INVALID_LINK_TEXT,
        signedIn
          ? [{ text: "OK" }]
          : [{ text: "Request a new link", onPress: requestNewLink }, { text: "OK", style: "cancel" }],
      );
      break;
    case "unavailable":
      Alert.alert("Could not open the link", "Check your connection, then open the link in the email again.");
      break;
    case "confirmed":
      Alert.alert("Email confirmed", "Your email address is confirmed.");
      break;
    default:
      // recovery_ready: the navigator shows the reset screen. stale: nothing.
      break;
  }
}

export function AuthLinkHost() {
  const { isLoading, session } = useAuth();
  const router = useRouter();
  const recovery = useRecoverySnapshot();
  // A link waits for the startup resolution of an earlier recovery (see recovery-startup.ts).
  const ready = !isLoading && recovery.phase !== "resolving";
  const notice = useSyncExternalStore(
    authLinkHandler.subscribeNotice,
    authLinkHandler.getNotice,
    authLinkHandler.getNotice,
  );

  useEffect(() => {
    if (!ready) {
      return undefined;
    }

    void authLinkHandler.drain();

    return authLinkHandler.subscribePending(() => {
      void authLinkHandler.drain();
    });
  }, [ready]);

  useEffect(() => {
    if (!notice) {
      return;
    }

    authLinkHandler.acknowledge(notice.id);
    showNotice(notice.outcome, session !== null, () => router.push("/forgot-password"));
  }, [notice, session, router]);

  return null;
}
