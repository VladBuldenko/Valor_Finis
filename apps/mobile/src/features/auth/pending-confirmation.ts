// The address a sign-up (or a resend) was just sent for, kept in memory only so the
// "check your email" screen can name it. Never persisted, never put in a route or a
// URL, cleared when the screen is left or a session starts. Pure.
let pendingEmail: string | null = null;

export const pendingConfirmation = {
  set(email: string): void {
    pendingEmail = email;
  },
  get(): string | null {
    return pendingEmail;
  },
  clear(): void {
    pendingEmail = null;
  },
};

// Where a signed-out user should land after a flow that ends their session on
// purpose (leaving a password recovery). A guarded route cannot be navigated to
// before the session has ended, so the target waits here and the root navigator
// applies it once, when it is signed out. In memory only; one of the fixed paths.
export type SignedOutLanding = "/sign-in" | "/forgot-password";

let landing: SignedOutLanding | null = null;

export const signedOutLanding = {
  set(path: SignedOutLanding): void {
    landing = path;
  },
  consume(): SignedOutLanding | null {
    const path = landing;

    landing = null;

    return path;
  },
  clear(): void {
    landing = null;
  },
};
