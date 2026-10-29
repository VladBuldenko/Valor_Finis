import type { QueryClient } from "@tanstack/react-query";

import { createAppQueryClient, isRetiredQueryClient, resetPrivateQueryData } from "./query-client.ts";

// Owns the one QueryClient of the current signed-in user. When the user
// changes the client is retired and a fresh one takes over, so every callback
// that captured the old client (screens get it from useQueryClient() while
// rendering) can only touch a dead cache, never the next user's.
export class SessionQueryClient {
  private current: QueryClient = createAppQueryClient();
  private readonly listeners = new Set<() => void>();

  get = (): QueryClient => this.current;

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
    this.listeners.forEach((listener) => listener());
  }
}
