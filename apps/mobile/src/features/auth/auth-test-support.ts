// Fakes for the AuthProvider-lifecycle tests (not imported by app code).
import type { AuthClientLike } from "./auth-session.ts";

export type FakeSession = { user: { id: string }; access_token: string };

export const session = (id: string, token = `token-${id}`): FakeSession => ({
  user: { id },
  access_token: token,
});

export type Deferred<T> = { promise: Promise<T>; resolve: (value: T) => void };

export function deferred<T>(): Deferred<T> {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((done) => { resolve = done; });

  return { promise, resolve };
}

type Callback = (event: string, session: FakeSession | null) => void;

// A Supabase-like auth client: getSession() waits for the test, events are
// emitted by the test, and every callback ever registered is remembered so a
// test can invoke one AFTER its subscription was unsubscribed (a late callback).
export function createFakeAuth() {
  const restores: Deferred<{ data: { session: FakeSession | null }; error: unknown }>[] = [];
  const active = new Set<Callback>();
  const registered: Callback[] = [];
  const calls = { getSession: 0, onAuthStateChange: 0, unsubscribed: 0 };

  const client: AuthClientLike<FakeSession> = {
    getSession: () => {
      calls.getSession += 1;

      const pending = deferred<{ data: { session: FakeSession | null }; error: unknown }>();

      restores.push(pending);

      return pending.promise;
    },
    onAuthStateChange: (callback) => {
      calls.onAuthStateChange += 1;
      active.add(callback);
      registered.push(callback);

      return {
        data: {
          subscription: {
            unsubscribe: () => {
              calls.unsubscribed += 1;
              active.delete(callback);
            },
          },
        },
      };
    },
  };

  return {
    client,
    calls,
    restores,
    registered,
    // Delivers an event to every still-subscribed callback.
    emit(next: FakeSession | null): void {
      [...active].forEach((callback) => callback("EVENT", next));
    },
    resolveRestore(index: number, restored: FakeSession | null): void {
      restores[index].resolve({ data: { session: restored }, error: null });
    },
  };
}
