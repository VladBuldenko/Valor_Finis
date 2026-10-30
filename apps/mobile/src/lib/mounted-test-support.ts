// Mounted-React harness for the session lifecycle tests (not imported by app
// code). It mounts a component that uses the REAL TanStack hooks (useQuery,
// useMutation, useQueryClient) under the REAL SessionScope, SessionQueryClient,
// SessionBoundary and API transport, with a scripted fetch. It deliberately
// does not include Supabase, AuthProvider or Expo Router.
import { QueryClientProvider, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient, UseMutationResult, UseQueryResult } from "@tanstack/react-query";
import { createElement, useEffect, useState, useSyncExternalStore, type ReactElement, type ReactNode } from "react";
import TestRenderer from "react-test-renderer";

import { createApiTransport } from "../api/api-transport.ts";
import { SessionBoundary } from "../api/session-boundary.ts";
import type { SessionIdentity } from "../api/session-lifecycle.ts";
import { SessionQueryClient } from "./session-query-client.ts";
import { SessionScope } from "./session-scope.ts";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// react-test-renderer 19 logs a deprecation notice on every import; it is the
// only maintained way to mount hooks without a DOM or a native runtime.
const originalConsoleError = console.error;

console.error = (...args: unknown[]) => {
  if (typeof args[0] === "string" && args[0].includes("react-test-renderer is deprecated")) {
    return;
  }

  originalConsoleError(...args);
};

export const { act } = TestRenderer;

export const USER_A: SessionIdentity = { userId: "user-a", accessToken: "a-token" };
export const USER_A_SECOND: SessionIdentity = { userId: "user-a", accessToken: "a-token-2" };
export const USER_B: SessionIdentity = { userId: "user-b", accessToken: "b-token" };

export type Deferred<T> = { promise: Promise<T>; resolve: (value: T) => void };

export function deferred<T>(): Deferred<T> {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((done) => { resolve = done; });

  return { promise, resolve };
}

export type Receipt = { id: string; owner: string };

export type Instance = {
  id: number;
  client: QueryClient;
  mounted: boolean;
  events: string[];
  renders: number;
  query: UseQueryResult<{ owner: string; n: number }> | null;
  mutation: UseMutationResult<Receipt, Error, void> | null;
};

export function createMountedWorld() {
  const holder = new SessionQueryClient();
  const boundary = new SessionBoundary(() => holder.rotate());
  const auth: { session: SessionIdentity | null } = { session: USER_A };
  // What AuthProvider's state is for the screens: authenticated screens exist
  // only while a session does (Stack.Protected in the real app).
  const authListeners = new Set<() => void>();
  const authSnapshot = { current: auth.session };
  const subscribeAuth = (listener: () => void) => {
    authListeners.add(listener);

    return () => {
      authListeners.delete(listener);
    };
  };
  const instances: Instance[] = [];
  const navigations: { instance: number; path: string }[] = [];
  const http: { user: string; method: string; path: string }[] = [];
  const gates = new Map<string, Deferred<void>>(); // per-user POST gate
  const counters = { get: 0 };

  const transport = createApiTransport({
    baseUrl: "https://api.test",
    boundary,
    sleep: async () => undefined,
    getSession: async () => auth.session,
    onUnauthorized: async () => undefined,
    fetch: async (url, init) => {
      const token = new Headers(init.headers).get("Authorization") ?? "";
      const user = token === "Bearer b-token" ? "user-b" : "user-a";
      const method = init.method ?? "GET";

      http.push({ user, method, path: url.replace("https://api.test", "") });

      if (method === "POST") {
        await gates.get(user)?.promise;

        return new Response(JSON.stringify({ id: `r-${user}`, owner: user }), { status: 200 });
      }

      counters.get += 1;

      return new Response(JSON.stringify({ owner: user, n: counters.get }), { status: 200 });
    },
  });

  boundary.applyAuthEvent(auth.session?.userId ?? null, auth.session?.accessToken ?? null);

  function Probe(): ReactElement | null {
    const client = useQueryClient();
    const [record] = useState<Instance>(() => {
      const created: Instance = {
        id: instances.length + 1,
        client,
        mounted: true,
        events: [],
        renders: 0,
        query: null,
        mutation: null,
      };

      instances.push(created);

      return created;
    });
    const query = useQuery({
      queryKey: ["items"],
      queryFn: () => transport.request<{ owner: string; n: number }>("/api/v1/items"),
    });
    const mutation = useMutation<Receipt, Error, void>({
      mutationFn: () =>
        transport.request<Receipt>("/api/v1/receipts/process", { method: "POST", body: "{}" }),
      onSuccess: (data) => {
        record.events.push(`success:${data.owner}`);
        client.setQueryData(["receipts", "detail", data.id], data);
        navigations.push({ instance: record.id, path: `/receipts/${data.id}` });
      },
      onError: () => {
        record.events.push("error");
      },
      onSettled: () => {
        record.events.push("settled");
      },
    });

    record.renders += 1;
    record.query = query;
    record.mutation = mutation;

    useEffect(
      () => () => {
        record.mounted = false;
      },
      [record],
    );

    return null;
  }

  function AuthGate(props: { children?: ReactNode }): ReactElement | null {
    const session = useSyncExternalStore(subscribeAuth, () => authSnapshot.current);

    return session ? createElement("authenticated", null, props.children) : null;
  }

  const current = (): Instance => {
    const live = instances.filter((instance) => instance.mounted);

    if (live.length !== 1) {
      throw new Error(`expected exactly one mounted probe, found ${live.length}`);
    }

    return live[0];
  };

  async function settle(ms = 25): Promise<void> {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, ms));
    });
  }

  async function mount(scope?: (children: ReactNode) => ReactElement): Promise<TestRenderer.ReactTestRenderer> {
    let renderer: TestRenderer.ReactTestRenderer | null = null;

    await act(async () => {
      const children = createElement(AuthGate, null, createElement(Probe));

      renderer = TestRenderer.create(
        scope ? scope(children) : createElement(SessionScope, { holder }, children),
      );
    });
    await settle();

    if (!renderer) {
      throw new Error("renderer was not created");
    }

    return renderer;
  }

  // Applies an authoritative auth event the way the coordinator does: the
  // session the transport reads is updated, then the boundary adopts it.
  async function authEvent(session: SessionIdentity | null): Promise<void> {
    await act(async () => {
      auth.session = session;
      // Same order as the auth coordinator: the boundary adopts first, then the
      // UI is told.
      boundary.applyAuthEvent(session?.userId ?? null, session?.accessToken ?? null);
      authSnapshot.current = session;
      authListeners.forEach((listener) => listener());
    });
    await settle();
  }

  async function startMutation(): Promise<void> {
    await act(async () => {
      current().mutation?.mutate();
    });
    await settle(10);
  }

  // The unkeyed variant: what app/_layout.tsx did before SR03 (a provider whose
  // client prop changes while the subtree stays mounted).
  const unkeyedScope = (children: ReactNode): ReactElement =>
    createElement(UnkeyedScope, { holder }, children);

  function UnkeyedScope(props: { holder: SessionQueryClient; children?: ReactNode }): ReactElement {
    const [client, setClient] = useState(props.holder.get());

    useEffect(
      () => props.holder.subscribe(() => setClient(props.holder.get())),
      [props.holder],
    );

    return createElement(QueryClientProvider, { client }, props.children);
  }

  return {
    holder,
    boundary,
    auth,
    instances,
    navigations,
    http,
    gates,
    transport,
    current,
    settle,
    mount,
    authEvent,
    startMutation,
    unkeyedScope,
  };
}
