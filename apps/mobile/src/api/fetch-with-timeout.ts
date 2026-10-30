// A fetch with ONE overall deadline. auth-js has no request timeout, and a
// sign-out holds the app's auth operation queue while its server call is in
// flight (to keep a later sign-in out of the window in which the stored session
// is read, revoked and removed). Without a bound, one hung request would block
// signing in again.
//
// The deadline covers dispatch, waiting for headers AND reading the body: the
// body is buffered inside the deadline and handed back as a fresh, complete
// Response. The returned promise is settled by the deadline itself (a race), not
// by the underlying fetch honouring AbortSignal, so a fetch that ignores abort
// cannot hold it open. Whatever the abandoned fetch or body read does later is
// swallowed here and never reaches auth-js.
//
// Why queue safety survives: a timeout only makes THIS request fail. auth-js
// receives an ordinary network error inside its own operation, finishes that
// operation itself (a sign-out still removes the local session) and only then
// does the app queue slot end. The queue is never released ahead of the
// operation, so no old operation can touch the session after a later one starts.

// Statuses a Response cannot carry a body for.
const NULL_BODY_STATUSES = new Set([101, 204, 205, 304]);

function abortError(name: "AbortError" | "TimeoutError", message: string): Error {
  const error = new Error(message);

  error.name = name;

  return error;
}

export function createFetchWithTimeout(
  baseFetch: typeof fetch,
  timeoutMs: number,
): typeof fetch {
  return (input, init) =>
    new Promise<Response>((resolve, reject) => {
      const controller = new AbortController();
      const callerSignal = init?.signal ?? undefined;
      let settled = false;
      let timer: ReturnType<typeof setTimeout> | undefined;

      // The only way out. Later calls (late fetch, late body, late abort) are no-ops.
      function settle(outcome: () => void, abortUnderlying: boolean): void {
        if (settled) {
          return;
        }

        settled = true;
        clearTimeout(timer);
        callerSignal?.removeEventListener("abort", onCallerAbort);

        if (abortUnderlying) {
          controller.abort();
        }

        outcome();
      }

      function fail(error: Error): void {
        settle(() => reject(error), true);
      }

      function onCallerAbort(): void {
        fail(abortError("AbortError", "The request was aborted."));
      }

      if (callerSignal?.aborted) {
        onCallerAbort();

        return;
      }

      callerSignal?.addEventListener("abort", onCallerAbort, { once: true });
      timer = setTimeout(
        () => fail(abortError("TimeoutError", `The request timed out after ${timeoutMs} ms.`)),
        timeoutMs,
      );

      const run = async (): Promise<void> => {
        const response = await baseFetch(input, { ...init, signal: controller.signal });
        const body = NULL_BODY_STATUSES.has(response.status) ? null : await response.text();

        // Rebuilt, not passed through, so the caller can no longer wait on the network.
        settle(
          () =>
            resolve(
              new Response(body, {
                status: response.status,
                statusText: response.statusText,
                headers: response.headers,
              }),
            ),
          false,
        );
      };

      // Every rejection is handled: before the deadline it fails the request
      // (original error preserved), after it nothing is left to fail.
      run().catch((error: unknown) => {
        fail(error instanceof Error ? error : new Error(String(error)));
      });
    });
}
