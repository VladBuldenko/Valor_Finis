// A fetch that gives up. auth-js has no request timeout, and a sign-out holds
// the app's auth operation queue while its server call is in flight (to keep
// a later sign-in out of the window in which the stored session is read, revoked
// and removed). Without a bound, one hung request would block signing in again.
// On timeout the request is aborted; auth-js then still removes the local session.
export function createFetchWithTimeout(
  baseFetch: typeof fetch,
  timeoutMs: number,
): typeof fetch {
  return (input, init) => {
    const controller = new AbortController();
    const callerSignal = init?.signal;
    const onCallerAbort = () => controller.abort();
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    if (callerSignal?.aborted) {
      controller.abort();
    } else {
      callerSignal?.addEventListener("abort", onCallerAbort, { once: true });
    }

    return baseFetch(input, { ...init, signal: controller.signal }).finally(() => {
      clearTimeout(timer);
      callerSignal?.removeEventListener("abort", onCallerAbort);
    });
  };
}
