// MF-4: what the router is allowed to see of an incoming URL. Pure.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { redirectIncomingUrl } from "./native-intent.ts";

const LINK = "valorfinis://auth/callback#access_token=SECRET&refresh_token=SECRET2&type=recovery";

describe("redirectIncomingUrl", () => {
  it("an auth link is claimed and the router sees only the root (cold start)", () => {
    const seen: string[] = [];
    const path = redirectIncomingUrl((url) => { seen.push(url); return true; }, { path: LINK, initial: true });

    assert.equal(path, "/");
    assert.deepEqual(seen, [LINK]);
    assert.doesNotMatch(path, /SECRET/);
  });

  it("an auth link in a running app is not routed at all (empty path)", () => {
    assert.equal(redirectIncomingUrl(() => true, { path: LINK, initial: false }), "");
  });

  it("every other URL passes through unchanged", () => {
    assert.equal(redirectIncomingUrl(() => false, { path: "valorfinis://goals/1", initial: true }), "valorfinis://goals/1");
    assert.equal(redirectIncomingUrl(() => false, { path: "/rules", initial: false }), "/rules");
  });
});
