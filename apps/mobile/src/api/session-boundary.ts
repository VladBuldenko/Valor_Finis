// Marks the lifetime of one signed-in user's data on this device.
//
// Every request is bound to the epoch that was current when it started. When
// the signed-in user changes (sign-out, account switch) the epoch advances,
// requests of the old epoch are aborted, and `onReset` wipes the private
// client-side data. A response that still arrives afterwards fails the
// `isCurrent` check in the transport, so it can never be returned to a query
// and repopulate the cache of the next user.
//
// A token refresh for the same user is NOT a boundary change.

export type BoundarySnapshot = {
  readonly epoch: number;
  readonly signal: AbortSignal;
};

export class SessionBoundary {
  private userId: string | null = null;
  private epoch = 0;
  private controller = new AbortController();
  private readonly onReset: () => void;

  constructor(onReset: () => void) {
    this.onReset = onReset;
  }

  snapshot(): BoundarySnapshot {
    return { epoch: this.epoch, signal: this.controller.signal };
  }

  isCurrent(snapshot: BoundarySnapshot): boolean {
    return snapshot.epoch === this.epoch;
  }

  // Reports the user that is signed in now (null = nobody). Returns true when
  // the previous user was replaced or signed out, in which case the old epoch
  // has been aborted and the private data reset.
  //
  // The first user seen after "nobody" is only adopted: every way to leave a
  // signed-in state (including sign-out) already reset the data, so nothing
  // of another user can exist yet, and resetting here would cancel the very
  // request that is reporting the user.
  observe(userId: string | null): boolean {
    if (userId === this.userId) {
      return false;
    }

    const previousUserId = this.userId;

    this.userId = userId;

    if (previousUserId === null) {
      return false;
    }

    this.epoch += 1;

    const previous = this.controller;

    this.controller = new AbortController();
    previous.abort();
    this.onReset();

    return true;
  }
}
