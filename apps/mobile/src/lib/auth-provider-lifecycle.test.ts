// MF2-SR08-T03: the same effect, mounted. A component runs startAuthSession in
// a useEffect exactly like AuthProvider does, under StrictMode (React runs
// setup -> cleanup -> setup in development) and through unmount / remount.
// Does not cover the real supabase-js client.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { createElement, StrictMode, useEffect, type ReactElement } from "react";

import { SessionBoundary } from "../api/session-boundary.ts";
import type { AuthState } from "../features/auth/auth-coordinator.ts";
import { startAuthSession } from "../features/auth/auth-session.ts";
import { createFakeAuth, session, type FakeSession } from "../features/auth/auth-test-support.ts";
import { act } from "./mounted-test-support.ts";
import TestRenderer from "react-test-renderer";
import { SessionQueryClient } from "./session-query-client.ts";

function setup() {
  const holder = new SessionQueryClient();
  const boundary = new SessionBoundary(() => holder.rotate());
  const auth = createFakeAuth();
  const published: { who: string; state: AuthState<FakeSession> }[] = [];

  function Provider(props: { who: string }): ReactElement | null {
    useEffect(
      () =>
        startAuthSession<FakeSession>({
          auth: auth.client,
          boundary,
          publish: (state) => published.push({ who: props.who, state }),
        }),
      [props.who],
    );

    return null;
  }

  async function mount(who: string, strict: boolean) {
    let renderer: TestRenderer.ReactTestRenderer | null = null;

    await act(async () => {
      const element = createElement(Provider, { who });

      renderer = TestRenderer.create(strict ? createElement(StrictMode, null, element) : element);
    });

    if (!renderer) {
      throw new Error("not mounted");
    }

    return renderer as TestRenderer.ReactTestRenderer;
  }

  const unmount = (renderer: TestRenderer.ReactTestRenderer) =>
    act(async () => {
      renderer.unmount();
    });
  const settle = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });

  return { holder, boundary, auth, published, mount, unmount, settle };
}

describe("SR08-T03: effect cleanup and remount", () => {
  it("StrictMode setup / cleanup / setup: only the second setup is alive", async () => {
    const w = setup();
    const renderer = await w.mount("provider", true);

    assert.equal(w.auth.calls.getSession, 2, "the effect ran twice (setup, cleanup, setup)");
    assert.equal(w.auth.calls.unsubscribed, 1, "the first subscription was cleaned up");

    w.auth.resolveRestore(0, session("user-a")); // the FIRST setup's restore
    w.auth.resolveRestore(1, session("user-b")); // the live setup's restore
    await w.settle();

    assert.equal(w.boundary.snapshot().userId, "user-b", "the cleaned-up setup cannot adopt A");
    assert.equal(w.published.length, 1);
    assert.equal(w.published[0].state.session?.user.id, "user-b");

    await w.unmount(renderer);
  });

  it("unmount makes every late restore and event inert; a remount is authoritative", async () => {
    const w = setup();
    const first = await w.mount("first", false);

    await w.unmount(first); // the first provider's restore (#0) is still pending

    const second = await w.mount("second", false);

    w.auth.emit(session("user-b"));
    await w.settle();

    const publishedBefore = w.published.length;
    const resetsBefore = w.holder.getSnapshot().generation;

    w.auth.resolveRestore(0, session("user-a")); // obsolete
    w.auth.registered[0]("EVENT", session("user-a")); // late callback of the first subscription
    await w.settle();

    assert.equal(w.boundary.snapshot().userId, "user-b");
    assert.equal(w.published.length, publishedBefore);
    assert.equal(w.holder.getSnapshot().generation, resetsBefore, "no QueryClient rotation was caused");

    await w.unmount(second);

    w.auth.registered[1]("EVENT", session("user-a")); // after the last provider unmounted
    assert.equal(w.boundary.snapshot().userId, "user-b", "nobody is authoritative any more");
  });

  it("a normal mount restores a valid session once", async () => {
    const w = setup();
    const renderer = await w.mount("only", false);

    w.auth.resolveRestore(0, session("user-a"));
    await w.settle();

    assert.equal(w.boundary.snapshot().userId, "user-a");
    assert.equal(w.published.length, 1);
    assert.equal(w.holder.getSnapshot().generation, 0, "first adoption does not rotate");

    await w.unmount(renderer);
  });
});
