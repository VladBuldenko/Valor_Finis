// Pull-to-refresh for a screen that shows data from one or several queries
// (VF-MOB-REFRESH-RETRY). Written without React Native imports so the Node
// runner can mount it.
//
// A refresh only RE-READS: it calls the queries' refetch and nothing else, so it
// can never send a financial write. While one refresh is running another pull is
// ignored (no refresh storm), and each refetch is asked not to cancel a request
// that is already in flight.
import { useEffect, useRef, useState } from "react";

export type Refetcher = () => Promise<unknown>;

type Refetchable = { refetch: (options?: { cancelRefetch?: boolean }) => Promise<unknown> };

// An in-flight request is reused instead of cancelled and restarted.
export const refetcherOf = (query: Refetchable): Refetcher => () => query.refetch({ cancelRefetch: false });

export type RefreshCoordinator = {
  isRunning: () => boolean;
  // null when a refresh is already running (the new request is dropped).
  run: (getRefetchers: () => readonly Refetcher[]) => Promise<void> | null;
};

export function createRefreshCoordinator(): RefreshCoordinator {
  let running: Promise<void> | null = null;

  return {
    isRunning: () => running !== null,
    run(getRefetchers) {
      if (running !== null) {
        return null;
      }

      // Every refetcher is started right away; one that throws or rejects does
      // not stop the others (TanStack reports its failure on the query itself).
      const started = getRefetchers().map(
        (refetch) =>
          new Promise<unknown>((resolve) => {
            resolve(refetch());
          }),
      );

      running = Promise.allSettled(started).then(() => undefined);
      void running.then(() => {
        running = null;
      });

      return running;
    },
  };
}

export type ScreenRefresh = { refreshing: boolean; onRefresh: () => void };

export function useScreenRefresh(getRefetchers: () => readonly Refetcher[]): ScreenRefresh {
  const coordinator = useRef(createRefreshCoordinator()).current;
  const mounted = useRef(true);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    mounted.current = true;

    return () => {
      mounted.current = false;
    };
  }, []);

  const onRefresh = (): void => {
    const done = coordinator.run(getRefetchers);

    if (done === null) {
      return;
    }

    setRefreshing(true);
    void done.then(() => {
      if (mounted.current) {
        setRefreshing(false);
      }
    });
  };

  return { refreshing, onRefresh };
}
