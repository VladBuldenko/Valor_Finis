import { QueryClient } from "@tanstack/react-query";

// Retries are owned by the API transport (GET only, bounded, transient
// failures only; see api-transport.ts). TanStack Query's own retry would
// multiply those attempts and could resend nothing safely, so it is off for
// queries and mutations alike.
export function createAppQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

export const queryClient = createAppQueryClient();

// Drops every cached query and mutation: used when the signed-in user
// changes, so no data of one user can be shown to the next. clear() destroys
// the queries, which also cancels their in-flight fetches; the transport
// additionally aborts the old user's requests and refuses to deliver a late
// response (session-boundary.ts).
export function resetPrivateQueryData(client: QueryClient): void {
  client.clear();
}
