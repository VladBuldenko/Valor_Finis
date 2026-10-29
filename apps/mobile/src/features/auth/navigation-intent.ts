// Remembers where the user was when the session was ended by the server (an
// invalid session), so a successful sign-in can return there. Only a
// sanitized in-app path is ever stored, never a query string, token or URL,
// and it is restored only for the SAME user: a different account that signs in
// next must not land on the previous user's screen.

const MAX_PATH_LENGTH = 200;
const INTENT_TTL_MS = 30 * 60 * 1000;
// Plain route segments only: no query, fragment, scheme, encoding or dots.
const SAFE_PATH = /^\/[A-Za-z0-9_\-/]*$/;

export function sanitizeReturnPath(path: unknown): string | null {
  if (typeof path !== "string" || path.length > MAX_PATH_LENGTH) {
    return null;
  }

  if (path === "/" || path.startsWith("//") || !SAFE_PATH.test(path)) {
    return null;
  }

  if (path === "/sign-in" || path.startsWith("/sign-in/")) {
    return null;
  }

  return path;
}

type Tracked = { userId: string; path: string };
type Pending = Tracked & { savedAt: number };

export function createNavigationIntentStore(now: () => number = Date.now) {
  let tracked: Tracked | null = null;
  let pending: Pending | null = null;

  return {
    // Called as the signed-in user navigates.
    track(userId: string, path: string): void {
      const safe = sanitizeReturnPath(path);

      if (safe) {
        tracked = { userId, path: safe };
      }
    },

    // The session was ended because the server rejected it: keep the last
    // location for re-authentication.
    captureOnInvalidation(): void {
      pending = tracked ? { ...tracked, savedAt: now() } : null;
      tracked = null;
    },

    // A deliberate sign-out, or any other end of session: keep nothing.
    discard(): void {
      tracked = null;
      pending = null;
    },

    // The path to restore for `userId`, once. Any call consumes the intent, so
    // a different user's sign-in also erases it.
    consumeFor(userId: string): string | null {
      const intent = pending;

      pending = null;
      tracked = null;

      if (!intent || intent.userId !== userId || now() - intent.savedAt > INTENT_TTL_MS) {
        return null;
      }

      return intent.path;
    },
  };
}

export const navigationIntent = createNavigationIntentStore();
