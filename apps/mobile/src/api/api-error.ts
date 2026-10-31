// Typed error for every failure of apiRequest (api-client.ts).
//
// Backwards compatibility: an HTTP failure keeps the exact historical message
// `API request failed: <status> <body>`, so the existing helpers and screens
// that parse error.message (api-error-message.ts, goal/category/transfer
// code) keep working unchanged. New code should branch on `kind` / `status`
// / `code` instead of parsing the message.

export type ApiErrorKind =
  // The server answered with a non-2xx status (other than a handled 401).
  | "http"
  // The server answered 401 for a request that carried a session token.
  | "unauthorized"
  // There was no session, so no request was sent.
  | "unauthenticated"
  // The overall deadline (all attempts and the response body) elapsed.
  | "timeout"
  // The caller aborted, or the session changed while the request was running.
  | "cancelled"
  // fetch itself failed (no connection, DNS, TLS, reset).
  | "network"
  // A 2xx response whose body could not be read as JSON.
  | "malformed_response";

export type ApiErrorInit = {
  kind: ApiErrorKind;
  message: string;
  status?: number | null;
  detail?: string | null;
  code?: string | null;
  body?: string | null;
  cause?: unknown;
};

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  // HTTP status, or null when no response was received or usable.
  readonly status: number | null;
  // The backend's string `detail`, or null (non-JSON body, validation list).
  readonly detail: string | null;
  // The backend's optional stable error code (BE-1), or null.
  readonly code: string | null;
  // Raw response text for HTTP failures; null otherwise.
  readonly body: string | null;

  constructor(init: ApiErrorInit) {
    super(init.message, init.cause === undefined ? undefined : { cause: init.cause });
    this.name = "ApiError";
    this.kind = init.kind;
    this.status = init.status ?? null;
    this.detail = init.detail ?? null;
    this.code = init.code ?? null;
    this.body = init.body ?? null;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

// True for every authentication failure: no session, or the server's 401.
export function isAuthApiError(error: unknown): boolean {
  return (
    isApiError(error) &&
    (error.kind === "unauthorized" || error.kind === "unauthenticated")
  );
}

const CODE_PATTERN = /^[a-z][a-z0-9_]{0,63}$/;

// Reads `detail` (string only) and `code` (stable snake_case only) from a
// FastAPI error body. Never throws; anything unexpected yields nulls.
export function parseErrorBody(text: string): {
  detail: string | null;
  code: string | null;
} {
  try {
    const parsed = JSON.parse(text) as { detail?: unknown; code?: unknown } | null;
    const detail = parsed?.detail;
    const code = parsed?.code;

    return {
      detail: typeof detail === "string" && detail ? detail : null,
      code: typeof code === "string" && CODE_PATTERN.test(code) ? code : null,
    };
  } catch {
    return { detail: null, code: null };
  }
}

export function httpApiError(
  kind: "http" | "unauthorized",
  status: number,
  body: string,
): ApiError {
  const { detail, code } = parseErrorBody(body);

  return new ApiError({
    kind,
    status,
    detail,
    code,
    body,
    message: `API request failed: ${status} ${body}`,
  });
}
