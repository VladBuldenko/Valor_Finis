import {
  MutationCache,
  QueryClient,
  type DefaultedQueryObserverOptions,
  type DefaultError,
  type QueryKey,
  type QueryObserverOptions,
} from "@tanstack/react-query";

import { ApiError } from "../api/api-error.ts";

const retiredClients = new WeakSet<QueryClient>();

// Retries are owned by the API transport (GET only, bounded, transient
// failures only; see api-transport.ts). TanStack Query's own retry would
// multiply those attempts and could resend nothing safely, so it is off for
// queries and mutations alike.
//
// Mutation callbacks (useMutation onSuccess/onError/onSettled) belong to the
// mutation, not to the screen: they keep running after the screen unmounted
// and after the user signed out. Once a client is retired (the signed-in user
// changed):
//  * a NEW mutation never starts (onMutate halts before mutationFn runs, so a
//    stale callback cannot send a request under the next user's token);
//  * a running mutation never reaches the screen's callbacks (the cache-level
//    onSuccess/onError/onSettled hooks never settle; TanStack awaits them
//    before the screen's own callbacks);
//  * queries on it are inert: their queryFn is replaced by a rejection, so no
//    request is made and nothing is fetched into the dead cache.
// "Never settle" is deliberate and bounded: see docs/modules/mobile-api-client.md
// (resource ownership) and retired-client-lifecycle.test.ts.
class AppQueryClient extends QueryClient {
  override defaultQueryOptions<
    TQueryFnData = unknown,
    TError = DefaultError,
    TData = TQueryFnData,
    TQueryData = TQueryFnData,
    TQueryKey extends QueryKey = QueryKey,
    TPageParam = never,
  >(
    options:
      | QueryObserverOptions<TQueryFnData, TError, TData, TQueryData, TQueryKey, TPageParam>
      | DefaultedQueryObserverOptions<TQueryFnData, TError, TData, TQueryData, TQueryKey>,
  ): DefaultedQueryObserverOptions<TQueryFnData, TError, TData, TQueryData, TQueryKey> {
    const resolved = super.defaultQueryOptions(options);

    if (!retiredClients.has(this)) {
      return resolved;
    }

    return {
      ...resolved,
      queryFn: () =>
        Promise.reject(new ApiError({ kind: "cancelled", message: "Request was cancelled." })),
    };
  }
}

export function createAppQueryClient(): QueryClient {
  const owner: { client: QueryClient | null } = { client: null };
  const haltIfRetired = async (): Promise<void> => {
    if (owner.client && retiredClients.has(owner.client)) {
      await new Promise<never>(() => undefined);
    }
  };
  const client = new AppQueryClient({
    mutationCache: new MutationCache({
      onMutate: haltIfRetired,
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
