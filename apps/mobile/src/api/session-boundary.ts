// Marks the lifetime of one signed-in user's data on this device.
//
// OWNERSHIP MODEL
//  * Only AUTHORITATIVE authentication events change the boundary
//    (`applyAuthEvent`, called by the auth coordinator for Supabase's
//    onAuthStateChange / the initial restore). A request never does: what a
//    request read from `getSession()` may be stale by the time it resolves, so
//    it is never proof of a login.
//  * Every user-identity change (nobody -> A, A -> B, A -> nobody, B -> A)
//    advances the EPOCH. A request takes a snapshot (epoch + the user it
//    belongs to) BEFORE its asynchronous session lookup and must still pass
//    `ownsSession` afterwards and `isCurrent` before every dispatch. Comparing
//    user ids alone would let a request from the first "A" generation become
//    valid again after A -> B -> A; the epoch makes that impossible.
//  * A change away from a signed-in user aborts that epoch's requests and runs
//    `onReset` (retire the user's query client). A token refresh for the same
//    user is not a change.
//
// Late responses of an old epoch fail `isCurrent` in the transport, so they can
// never reach a query and repopulate the cache of the next user.

export type BoundarySnapshot = {
  readonly epoch: number;
  // The authoritative user when the snapshot was taken (null = nobody).
  readonly userId: string | null;
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
    return { epoch: this.epoch, userId: this.userId, signal: this.controller.signal };
  }

  isCurrent(snapshot: BoundarySnapshot): boolean {
    return snapshot.epoch === this.epoch;
  }

  // True when a session lookup that started under `snapshot` and returned a
  // session of `userId` still belongs to the live epoch and the same user.
  ownsSession(snapshot: BoundarySnapshot, userId: string): boolean {
    return snapshot.epoch === this.epoch && snapshot.userId === userId;
  }

  // The authoritative current user (null = nobody). Returns true when the
  // user changed. Leaving a signed-in user (to nobody or to another user)
  // aborts that epoch's requests and resets the private data; the first user
  // after "nobody" only advances the epoch, since signing out already reset.
  applyAuthEvent(userId: string | null): boolean {
    if (userId === this.userId) {
      return false;
    }

    const previousUserId = this.userId;
    const previous = this.controller;

    this.userId = userId;
    this.epoch += 1;
    this.controller = new AbortController();
    previous.abort();

    if (previousUserId !== null) {
      this.onReset();
    }

    return true;
  }
}
