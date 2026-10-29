import { MutationCache, QueryClient } from "@tanstack/react-query";

const retiredClients = new WeakSet<QueryClient>();

// Retries are owned by the API transport (GET only, bounded, transient
// failures only; see api-transport.ts). TanStack Query's own retry would
// multiply those attempts and could resend nothing safely, so it is off for
// queries and mutations alike.
//
// Mutation callbacks (useMutation onSuccess/onError/onSettled) belong to the
// mutation, not to the screen: they keep running after the screen unmounted
// and after the user signed out. Once a client is retired (the signed-in user
// changed), the cache-level hooks below never settle, so TanStack never
// reaches the screen's own callbacks: nothing of the previous user can write
// to the cache, navigate or refetch under the next user's session.
export function createAppQueryClient(): QueryClient {
  const owner: { client: QueryClient | null } = { client: null };
  const haltIfRetired = async (): Promise<void> => {
    if (owner.client && retiredClients.has(owner.client)) {
      await new Promise<never>(() => undefined);
    }
  };
  const client = new QueryClient({
    mutationCache: new MutationCache({
      onSuccess: haltIfRetired,
      onError: haltIfRetired,
      onSettled: haltIfRetired,
    }),
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  owner.client = client;

  return client;
}

// Ends a client's life: drops every cached query and mutation (clear() also
// cancels in-flight fetches) and halts the callbacks of its running
// mutations. Used when the signed-in user changes, so no data of one user
// can be shown to the next. The transport additionally aborts the old user's
// requests and refuses late responses (session-boundary.ts).
export function resetPrivateQueryData(client: QueryClient): void {
  retiredClients.add(client);
  client.clear();
}

export function isRetiredQueryClient(client: QueryClient): boolean {
  return retiredClients.has(client);
}
