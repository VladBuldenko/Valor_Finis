import type { QueryClient } from "@tanstack/react-query";

import { createAppQueryClient, isRetiredQueryClient, resetPrivateQueryData } from "./query-client.ts";

// Owns the one QueryClient of the current signed-in user. When the user
// changes the client is retired and a fresh one takes over, so every callback
// that captured the old client (screens get it from useQueryClient() while
// rendering) can only touch a dead cache, never the next user's.
export type SessionQueryClientSnapshot = {
  readonly client: QueryClient;
  // Advances on every rotation; used as the React key of the session subtree.
  readonly generation: number;
};

export class SessionQueryClient {
  private current: QueryClient = createAppQueryClient();
  private snapshot: SessionQueryClientSnapshot = { client: this.current, generation: 0 };
  private readonly listeners = new Set<() => void>();

  get = (): QueryClient => this.current;

  // Referentially stable between rotations (useSyncExternalStore contract).
  getSnapshot = (): SessionQueryClientSnapshot => this.snapshot;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);

    return () => {
      this.listeners.delete(listener);
    };
  };

  // True while `client` is the live client. Code that continues after an
  // await (navigation, follow-up requests) checks this before acting.
  isCurrent = (client: QueryClient): boolean => client === this.current && !isRetiredQueryClient(client);

  rotate(): void {
    resetPrivateQueryData(this.current);
    this.current = createAppQueryClient();
    this.snapshot = { client: this.current, generation: this.snapshot.generation + 1 };
    this.listeners.forEach((listener) => listener());
  }
}
