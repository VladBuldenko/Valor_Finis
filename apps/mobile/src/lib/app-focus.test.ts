// VF-MOB-REFRESH-RETRY: the AppState -> focus manager bridge (pure part).
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { installAppFocus } from "./app-focus.ts";

function rig(initial: string) {
  const reported: (boolean | undefined)[] = [];
  const listeners = new Set<(state: string) => void>();
  let state = initial;
  const stop = installAppFocus({
    focusManager: { setFocused: (focused) => { reported.push(focused); } },
    subscribeAppState: (listener) => {
      listeners.add(listener);

      return () => { listeners.delete(listener); };
    },
    getAppState: () => state,
  });
  const emit = (next: string) => { state = next; listeners.forEach((listener) => listener(next)); };

  return { reported, listeners, stop, emit };
}

describe("foreground transitions", () => {
  it("starting does not report a foreground", () => {
    const r = rig("active");

    assert.deepEqual(r.reported, []);
    assert.equal(r.listeners.size, 1);
  });

  it("background -> active reports exactly one 'focused'; inactive -> active too", () => {
    const r = rig("active");

    r.emit("background");
    r.emit("active");
    r.emit("inactive");
    r.emit("active");
    assert.deepEqual(r.reported, [false, true, false, true]);
  });

  it("repeated identical events are dropped", () => {
    const r = rig("active");

    r.emit("active");
    r.emit("active");
    r.emit("background");
    r.emit("background");
    r.emit("inactive");        // leaving the foreground again is not a new change
    r.emit("active");
    r.emit("active");
    assert.deepEqual(r.reported, [false, true]);
  });

  it("starting in the background reports focus only on the first real return", () => {
    const r = rig("background");

    r.emit("background");
    assert.deepEqual(r.reported, []);
    r.emit("active");
    assert.deepEqual(r.reported, [true]);
  });

  it("non-active states such as unknown or extension count as not focused", () => {
    const r = rig("active");

    r.emit("unknown");
    r.emit("active");
    assert.deepEqual(r.reported, [false, true]);
  });
});

describe("cleanup", () => {
  it("removes the listener and ignores anything after it", () => {
    const r = rig("active");

    r.stop();
    assert.equal(r.listeners.size, 0);
    r.emit("background");
    r.emit("active");
    assert.deepEqual(r.reported, []);
  });

  it("cleanup does not itself report a focus change (no refetch on teardown)", () => {
    const r = rig("background");

    r.stop();
    assert.deepEqual(r.reported, []);
  });

  it("installing twice yields two independent subscriptions that each clean up", () => {
    const a = rig("active");
    const b = rig("active");

    a.stop();
    assert.equal(a.listeners.size, 0);
    assert.equal(b.listeners.size, 1);
  });
});
