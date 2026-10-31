import { env } from "../config/env";
import { supabase } from "../lib/supabase";
import { sessionBoundary, sessionLifecycle } from "../lib/session-runtime";
import { createApiTransport, type ApiRequestOptions } from "./api-transport";

export { ApiError, isApiError, isAuthApiError } from "./api-error";
export type { ApiErrorKind } from "./api-error";
export type { ApiRequestOptions } from "./api-transport";

const transport = createApiTransport({
  baseUrl: env.apiUrl,
  fetch: (input, init) => fetch(input, init),
  getSession: async () => {
    const {
      data: { session },
      error,
    } = await supabase.auth.getSession();

    if (error) {
      throw error;
    }

    return session
      ? { userId: session.user.id, accessToken: session.access_token }
      : null;
  },
  boundary: sessionBoundary,
  onUnauthorized: (used, proof) => sessionLifecycle.handleUnauthorized(used, proof),
});

// The single entry point for FastAPI calls. See api-transport.ts for the
// timeout, retry and cancellation policy and session-lifecycle.ts for HTTP 401.
export function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  return transport.request<T>(path, options);
}
