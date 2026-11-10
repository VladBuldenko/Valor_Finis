// Runs for every URL the OS hands to the app, before Expo Router turns it into a
// route (cold start: initial = true; already running: initial = false).
//
// An auth link (`<scheme>://auth/callback#...`) carries a credential. It is given to
// the auth-link handler here and NEVER becomes a route, a route parameter or a
// history entry. The handler (driven by AuthLinkHost) turns it into a session and
// the navigator reacts to the result. Anything else passes through unchanged.
import { redirectIncomingUrl } from "../src/features/auth/native-intent";
import { authLinkHandler } from "../src/lib/auth-link-runtime";

export function redirectSystemPath(event: { path: string; initial: boolean }): string {
  return redirectIncomingUrl((url) => authLinkHandler.receive(url), event);
}
