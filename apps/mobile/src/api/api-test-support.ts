// Shared fakes for the API transport tests (not imported by app code).
import { createApiTransport, type FetchLike, type TransportPolicy } from "./api-transport.ts";
import { SessionBoundary } from "./session-boundary.ts";
import type { OwnershipProof, SessionIdentity } from "./session-lifecycle.ts";

export type Call = { url: string; init: RequestInit; headers: Headers };

export function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function never<T>(): Promise<T> {
  return new Promise<T>(() => undefined);
}

// A fetch that rejects when its signal aborts, like the real one.
export function hangUntilAborted(init: RequestInit): Promise<Response> {
  return new Promise<Response>((_resolve, reject) => {
    init.signal?.addEventListener("abort", () => reject(new Error("fetch aborted")), {
      once: true,
    });
  });
}

export function makeHarness(options: {
  respond: (call: Call, attempt: number) => Promise<Response>;
  session?: () => Promise<SessionIdentity | null>;
  onUnauthorized?: (used: SessionIdentity, proof: OwnershipProof) => Promise<unknown>;
  policy?: Partial<TransportPolicy>;
  sleep?: (ms: number, signal: AbortSignal) => Promise<void>;
  onReset?: () => void;
}) {
  const calls: Call[] = [];
  const sleeps: number[] = [];
  const unauthorized: SessionIdentity[] = [];
  const boundary = new SessionBoundary(options.onReset ?? (() => undefined));
  const session: SessionIdentity = { userId: "user-1", accessToken: "token-1" };

  boundary.applyAuthEvent(session.userId, session.accessToken); // the auth coordinator adopted the session

  const fetchLike: FetchLike = (url, init) => {
    const call: Call = { url, init, headers: new Headers(init.headers) };

    calls.push(call);

    return options.respond(call, calls.length);
  };

  const transport = createApiTransport({
    baseUrl: "https://api.test",
    fetch: fetchLike,
    getSession: options.session ?? (async () => session),
    boundary,
    onUnauthorized: async (used, proof) => {
      unauthorized.push(used);

      return options.onUnauthorized?.(used, proof);
    },
    sleep:
      options.sleep ??
      (async (ms) => {
        sleeps.push(ms);
      }),
    policy: options.policy,
  });

  return { transport, calls, sleeps, unauthorized, boundary, session };
}
