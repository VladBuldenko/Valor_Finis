// HTTP transport behind apiRequest (api-client.ts). Everything environmental
// (fetch, session, boundary, sleep) is injected so the timeout, retry and
// auth rules are testable in Node without Supabase or React Native.
//
// Policy summary:
//  * One overall deadline per call covers the session lookup, every attempt,
//    the retry waits and reading the response body: 30 s, 60 s for multipart.
//  * Only GET is ever retried, at most `maxRetries` times, only after a
//    network failure or HTTP 502/503/504, and only if the wait fits inside
//    the remaining deadline. POST/PATCH/PUT/DELETE and uploads get exactly one
//    network attempt, so a financial mutation is never sent twice by this
//    layer. 401/403/404/409/422, timeouts and cancellation are never retried.
//  * The session Authorization header cannot be overridden by the caller.

import { ApiError, httpApiError } from "./api-error.ts";
import type { SessionBoundary } from "./session-boundary.ts";
import type { SessionIdentity } from "./session-lifecycle.ts";

export type FetchLike = (input: string, init: RequestInit) => Promise<Response>;

export type TransportPolicy = {
  timeoutMs: number;
  multipartTimeoutMs: number;
  maxRetries: number;
  // Wait before retry n (0-based); the last entry repeats.
  retryDelaysMs: number[];
};

export const DEFAULT_TRANSPORT_POLICY: TransportPolicy = {
  timeoutMs: 30_000,
  multipartTimeoutMs: 60_000,
  maxRetries: 2,
  retryDelaysMs: [300, 900],
};

export type ApiRequestOptions = RequestInit & {
  // Overrides the default overall deadline for this call.
  timeoutMs?: number;
};

export type TransportDeps = {
  baseUrl: string;
  fetch: FetchLike;
  getSession: () => Promise<SessionIdentity | null>;
  boundary: SessionBoundary;
  // Called on HTTP 401 with the identity whose token was rejected.
  onUnauthorized: (used: SessionIdentity) => Promise<unknown>;
  sleep?: (ms: number, signal: AbortSignal) => Promise<void>;
  now?: () => number;
  policy?: Partial<TransportPolicy>;
};

const RETRYABLE_STATUSES = new Set([502, 503, 504]);

class AbortedError extends Error {
  constructor() {
    super("aborted");
    this.name = "AbortedError";
  }
}

// Rejects as soon as `signal` aborts, even when the underlying operation
// ignores the signal, so the deadline is a hard bound.
function abortable<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
  if (signal.aborted) {
    promise.catch(() => undefined);

    return Promise.reject(new AbortedError());
  }

  return new Promise<T>((resolve, reject) => {
    const onAbort = () => reject(new AbortedError());

    signal.addEventListener("abort", onAbort, { once: true });
    promise.then(
      (value) => {
        signal.removeEventListener("abort", onAbort);
        resolve(value);
      },
      (error: unknown) => {
        signal.removeEventListener("abort", onAbort);
        reject(error);
      },
    );
  });
}

function defaultSleep(ms: number, signal: AbortSignal): Promise<void> {
  return abortable(
    new Promise<void>((resolve) => {
      setTimeout(resolve, ms);
    }),
    signal,
  );
}

function buildHeaders(
  callerHeaders: HeadersInit | undefined,
  isFormData: boolean,
  accessToken: string,
): Headers {
  const headers = new Headers(callerHeaders);

  if (isFormData) {
    // The runtime must generate the multipart boundary itself.
    headers.delete("Content-Type");
  } else if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  // Set last and case-insensitively: a caller cannot replace the session token.
  headers.set("Authorization", `Bearer ${accessToken}`);

  return headers;
}

export function createApiTransport(deps: TransportDeps) {
  const policy: TransportPolicy = { ...DEFAULT_TRANSPORT_POLICY, ...deps.policy };
  const sleep = deps.sleep ?? defaultSleep;
  const now = deps.now ?? Date.now;

  async function request<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
    const { timeoutMs: timeoutOverride, signal: callerSignal, ...init } = options;
    const method = (init.method ?? "GET").toUpperCase();
    const isFormData = typeof FormData !== "undefined" && init.body instanceof FormData;
    const timeoutMs =
      timeoutOverride ?? (isFormData ? policy.multipartTimeoutMs : policy.timeoutMs);

    if (callerSignal?.aborted) {
      throw new ApiError({ kind: "cancelled", message: "Request was cancelled." });
    }

    const controller = new AbortController();
    const startedAt = now();
    const abort: { reason: "timeout" | "cancelled" | null } = { reason: null };

    const abortWith = (why: "timeout" | "cancelled") => {
      if (!controller.signal.aborted) {
        abort.reason = why;
        controller.abort();
      }
    };
    const onCallerAbort = () => abortWith("cancelled");
    const onBoundaryAbort = () => abortWith("cancelled");
    const timer = setTimeout(() => abortWith("timeout"), timeoutMs);

    callerSignal?.addEventListener("abort", onCallerAbort, { once: true });

    // Ownership: the snapshot is taken BEFORE the asynchronous session lookup.
    // The lookup result is only a claim; it counts only if the authoritative
    // session did not change meanwhile (session-boundary.ts).
    const snapshot = deps.boundary.snapshot();
    const boundarySignal = snapshot.signal;

    boundarySignal.addEventListener("abort", onBoundaryAbort, { once: true });

    try {
      const session = await abortable(deps.getSession(), controller.signal);

      if (!deps.boundary.isCurrent(snapshot)) {
        throw new AbortedError();
      }

      if (!session) {
        throw new ApiError({
          kind: "unauthenticated",
          message: "User is not authenticated.",
        });
      }

      // A stale lookup, or a session the auth coordinator has not adopted
      // (yet), is refused before any HTTP request and never touches the
      // boundary: requests observe, only auth events decide.
      if (!deps.boundary.ownsSession(snapshot, session.userId)) {
        throw new AbortedError();
      }

      const headers = buildHeaders(init.headers, isFormData, session.accessToken);
      const url = `${deps.baseUrl}${path}`;
      const canRetry = (attempt: number) =>
        method === "GET" && attempt < policy.maxRetries;

      // The wait before the next attempt, or null when it would not fit in
      // the remaining deadline (the last error is then reported instead).
      const retryDelay = (attempt: number): number | null => {
        const delay =
          policy.retryDelaysMs[Math.min(attempt, policy.retryDelaysMs.length - 1)] ?? 0;

        return delay < timeoutMs - (now() - startedAt) ? delay : null;
      };

      for (let attempt = 0; ; attempt += 1) {
        let response: Response;

        // Re-checked before every dispatch (also after retry waits).
        if (!deps.boundary.isCurrent(snapshot)) {
          throw new AbortedError();
        }

        try {
          response = await abortable(
            deps.fetch(url, { ...init, headers, signal: controller.signal }),
            controller.signal,
          );
        } catch (error) {
          if (controller.signal.aborted) {
            throw error;
          }

          const delay = canRetry(attempt) ? retryDelay(attempt) : null;

          if (delay !== null) {
            await sleep(delay, controller.signal);
            continue;
          }

          throw new ApiError({
            kind: "network",
            message: error instanceof Error ? error.message : "Network request failed",
            cause: error,
          });
        }

        if (!response.ok) {
          const delay =
            RETRYABLE_STATUSES.has(response.status) && canRetry(attempt)
              ? retryDelay(attempt)
              : null;

          if (delay !== null) {
            void response.body?.cancel().catch(() => undefined);
            await sleep(delay, controller.signal);
            continue;
          }

          const body = await abortable(response.text(), controller.signal);

          if (!deps.boundary.isCurrent(snapshot)) {
            throw new AbortedError();
          }

          if (response.status === 401) {
            // Never lets a failure of the check mask the 401 itself.
            await abortable(
              deps.onUnauthorized(session).catch(() => undefined),
              controller.signal,
            );

            throw httpApiError("unauthorized", 401, body);
          }

          throw httpApiError("http", response.status, body);
        }

        let result: T;

        if (response.status === 204) {
          result = undefined as T;
        } else {
          try {
            result = (await abortable(response.json(), controller.signal)) as T;
          } catch (error) {
            if (controller.signal.aborted) {
              throw error;
            }

            throw new ApiError({
              kind: "malformed_response",
              status: response.status,
              message: "The server returned an unreadable response.",
              cause: error,
            });
          }
        }

        // A response that arrives after the user changed must not reach the
        // caller (and so never the query cache of the new user).
        if (!deps.boundary.isCurrent(snapshot)) {
          throw new AbortedError();
        }

        return result;
      }
    } catch (error) {
      if (error instanceof ApiError) {
        throw error;
      }

      if (controller.signal.aborted || error instanceof AbortedError) {
        if (abort.reason === "timeout") {
          throw new ApiError({ kind: "timeout", message: "Request timed out.", cause: error });
        }

        throw new ApiError({ kind: "cancelled", message: "Request was cancelled.", cause: error });
      }

      throw error;
    } finally {
      clearTimeout(timer);
      callerSignal?.removeEventListener("abort", onCallerAbort);
      boundarySignal.removeEventListener("abort", onBoundaryAbort);
    }
  }

  return { request };
}
