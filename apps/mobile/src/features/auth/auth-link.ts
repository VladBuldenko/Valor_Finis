// Parses the links Supabase Auth sends by email (sign-up confirmation and password
// recovery) after they have been redirected to this app. Pure and Node-testable.
//
// The mobile Supabase client has `detectSessionInUrl: false`, so nothing reads the
// link for us: this module classifies it and the link handler (auth-link-handler.ts)
// establishes the session from it.
//
// What the link can look like depends on the Supabase project's settings and flow
// (staging checklist item A-08), so every known form is understood and anything else
// is refused instead of guessed:
//   * implicit flow:  <scheme>://auth/callback#access_token=..&refresh_token=..&type=recovery
//   * PKCE flow:      <scheme>://auth/callback?code=..
//   * token-hash:     <scheme>://auth/callback?token_hash=..&type=recovery
//   * an error:       <scheme>://auth/callback#error=access_denied&error_code=otp_expired&..
//
// SECURITY
//  * The result of parsing is the ONLY place a credential travels in. Nothing here
//    logs, and an error never carries any part of the URL: the reasons are fixed codes.
//  * Only the app's own scheme and the exact path `auth/callback` are accepted. Another
//    scheme, host or path is `ignore` (not ours), never "invalid".
//  * The server's error text (`error_description`) is never read: copy is ours.

export const AUTH_CALLBACK_PATH = "auth/callback";

export type LinkPurpose = "recovery" | "confirmation";

export type ParsedAuthLink =
  // Not a link for this module (other scheme/path). Nothing to do.
  | { kind: "ignore" }
  // Ours, but unusable: no recognizable credential, duplicated or oversized
  // parameters, or a purpose this app does not support.
  | { kind: "invalid"; reason: "malformed" | "unsupported" }
  // The auth server reported a failed link (expired, already used, denied).
  | { kind: "failed_link"; reason: "expired" | "denied" | "unknown" }
  | { kind: "session_tokens"; purpose: LinkPurpose; accessToken: string; refreshToken: string }
  // PKCE: the purpose is only known after the exchange.
  | { kind: "code"; code: string }
  | { kind: "token_hash"; purpose: LinkPurpose; tokenHash: string; otpType: "recovery" | "signup" | "email" };

export type ParseOptions = {
  // The app's own URL scheme(s), lower case, without "://".
  schemes: readonly string[];
  // Development only: Expo Go / dev-client links look like exp://host:port/--/auth/callback.
  allowExpoDevLinks?: boolean;
};

const MAX_URL_LENGTH = 8192;
const MAX_PARAMETERS = 24;
const TOKEN_PATTERN = /^[A-Za-z0-9._~+/=-]{1,4096}$/;
const CODE_PATTERN = /^[A-Za-z0-9._~-]{1,512}$/;
const HASH_PATTERN = /^[A-Za-z0-9_-]{8,256}$/;

// scheme://[/]auth/callback with an optional trailing slash, then the end, "?" or "#".
const APP_LINK = /^([a-z][a-z0-9+.-]*):\/\/\/?auth\/callback\/?(?=[?#]|$)/i;
const EXPO_DEV_LINK = /^(exps?):\/\/[^/?#]+\/--\/auth\/callback\/?(?=[?#]|$)/i;

function purposeOf(type: string | undefined): LinkPurpose | null {
  if (type === "recovery") {
    return "recovery";
  }

  // Supabase uses "signup" for a new account and "email" for the OTP form of the same
  // confirmation. Invites, magic links and e-mail changes are not supported.
  if (type === "signup" || type === "email") {
    return "confirmation";
  }

  return null;
}

// null = malformed (undecodable, repeated key, too many parameters).
function readParameters(part: string): Map<string, string> | null {
  const result = new Map<string, string>();

  if (part === "") {
    return result;
  }

  const pairs = part.split("&");

  if (pairs.length > MAX_PARAMETERS) {
    return null;
  }

  for (const pair of pairs) {
    if (pair === "") {
      continue;
    }

    const separator = pair.indexOf("=");
    const rawKey = separator === -1 ? pair : pair.slice(0, separator);
    const rawValue = separator === -1 ? "" : pair.slice(separator + 1);
    let key: string;
    let value: string;

    try {
      key = decodeURIComponent(rawKey.replace(/\+/g, " "));
      value = decodeURIComponent(rawValue.replace(/\+/g, " "));
    } catch {
      return null;
    }

    // A repeated key is ambiguous (which one is the credential?): refuse.
    if (result.has(key)) {
      return null;
    }

    result.set(key, value);
  }

  return result;
}

export function parseAuthLink(url: unknown, options: ParseOptions): ParsedAuthLink {
  if (typeof url !== "string" || url.length === 0) {
    return { kind: "ignore" };
  }

  const app = APP_LINK.exec(url);
  const dev = options.allowExpoDevLinks ? EXPO_DEV_LINK.exec(url) : null;
  const matched = app ?? dev;

  if (!matched) {
    return { kind: "ignore" };
  }

  const scheme = matched[1].toLowerCase();

  // `app` matched any scheme-shaped prefix; only the configured ones are ours.
  if (app && !dev && !options.schemes.includes(scheme)) {
    return { kind: "ignore" };
  }

  if (url.length > MAX_URL_LENGTH) {
    return { kind: "invalid", reason: "malformed" };
  }

  const rest = url.slice(matched[0].length);
  const hashAt = rest.indexOf("#");
  const query = hashAt === -1 ? rest : rest.slice(0, hashAt);
  const fragment = hashAt === -1 ? "" : rest.slice(hashAt + 1);
  const queryParameters = readParameters(query.startsWith("?") ? query.slice(1) : query);
  const fragmentParameters = readParameters(fragment);

  if (queryParameters === null || fragmentParameters === null) {
    return { kind: "invalid", reason: "malformed" };
  }

  const parameters = new Map<string, string>(queryParameters);

  for (const [key, value] of fragmentParameters) {
    // The same key in both places is ambiguous as well.
    if (parameters.has(key)) {
      return { kind: "invalid", reason: "malformed" };
    }

    parameters.set(key, value);
  }

  if (parameters.has("error") || parameters.has("error_code") || parameters.has("error_description")) {
    const code = parameters.get("error_code") ?? "";
    const error = parameters.get("error") ?? "";

    if (code === "otp_expired") {
      return { kind: "failed_link", reason: "expired" };
    }

    return { kind: "failed_link", reason: error === "access_denied" ? "denied" : "unknown" };
  }

  const accessToken = parameters.get("access_token");
  const refreshToken = parameters.get("refresh_token");
  const type = parameters.get("type");

  if (accessToken !== undefined || refreshToken !== undefined) {
    if (!accessToken || !refreshToken || !TOKEN_PATTERN.test(accessToken) || !TOKEN_PATTERN.test(refreshToken)) {
      return { kind: "invalid", reason: "malformed" };
    }

    if (type === undefined) {
      return { kind: "invalid", reason: "malformed" };
    }

    const purpose = purposeOf(type);

    return purpose === null
      ? { kind: "invalid", reason: "unsupported" }
      : { kind: "session_tokens", purpose, accessToken, refreshToken };
  }

  const tokenHash = parameters.get("token_hash");

  if (tokenHash !== undefined) {
    const purpose = purposeOf(type);

    if (!HASH_PATTERN.test(tokenHash) || type === undefined) {
      return { kind: "invalid", reason: "malformed" };
    }

    if (purpose === null) {
      return { kind: "invalid", reason: "unsupported" };
    }

    return {
      kind: "token_hash",
      purpose,
      tokenHash,
      otpType: type === "recovery" ? "recovery" : (type as "signup" | "email"),
    };
  }

  const code = parameters.get("code");

  if (code !== undefined) {
    return CODE_PATTERN.test(code) ? { kind: "code", code } : { kind: "invalid", reason: "malformed" };
  }

  return { kind: "invalid", reason: "malformed" };
}

// The redirect URL handed to Supabase (`redirectTo`). It must be listed in the
// Supabase project's redirect allowlist (a hosted setting this repository does not
// configure). The scheme comes from app.json (`expo.scheme`).
export function buildAuthRedirectUrl(scheme: string): string {
  return `${scheme}://${AUTH_CALLBACK_PATH}`;
}

// iOS and Android scheme rules, and "not the generic scaffold value".
const SCHEME_PATTERN = /^[a-z][a-z0-9+.-]{2,63}$/;
const GENERIC_SCHEMES: ReadonlySet<string> = new Set(["mobile", "app", "myapp", "exp", "exps", "http", "https"]);

export function isAppSpecificScheme(scheme: unknown): scheme is string {
  return typeof scheme === "string" && SCHEME_PATTERN.test(scheme) && !GENERIC_SCHEMES.has(scheme);
}
