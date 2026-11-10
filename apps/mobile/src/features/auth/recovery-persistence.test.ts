// MF-4 restart safety: the durable recovery record. In-memory storage, deterministic.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { RECOVERY_MARKER_KEY, createRecoveryPersistence, parseMarker } from "./recovery-persistence.ts";
import { memoryStorage } from "./recovery-test-support.ts";

describe("parseMarker", () => {
  it("accepts the two shapes", () => {
    assert.deepEqual(parseMarker('{"v":1,"phase":"active","userId":"u-1"}'), { v: 1, phase: "active", userId: "u-1" });
    assert.deepEqual(parseMarker('{"v":1,"phase":"verifying","priorUserId":null,"recoveryUserId":"u-2"}'), {
      v: 1,
      phase: "verifying",
      priorUserId: null,
      recoveryUserId: "u-2",
    });
  });

  it("refuses everything else", () => {
    for (const raw of ["", "not json", "null", "[]", "5", '{"v":2,"phase":"active","userId":"u"}', '{"v":1,"phase":"active"}', '{"v":1,"phase":"active","userId":""}', '{"v":1,"phase":"active","userId":"a b"}', '{"v":1,"phase":"other"}', '{"v":1,"phase":"verifying","priorUserId":5,"recoveryUserId":null}', '{"v":1,"phase":"verifying"}']) {
      assert.equal(parseMarker(raw), null, raw);
    }
  });
});

describe("recovery persistence", () => {
  it("reads none, a marker, and reports corrupt or failing storage as unreadable", async () => {
    const m = memoryStorage();
    const persistence = createRecoveryPersistence(m.storage);

    assert.deepEqual(await persistence.read(), { kind: "none" });
    await persistence.writeActive("u-1");
    assert.deepEqual(await persistence.read(), { kind: "marker", marker: { v: 1, phase: "active", userId: "u-1" } });
    m.data.set(RECOVERY_MARKER_KEY, "{broken");
    assert.deepEqual(await persistence.read(), { kind: "unreadable" });
    m.data.delete(RECOVERY_MARKER_KEY);
    m.faults.read = true;
    assert.deepEqual(await persistence.read(), { kind: "unreadable" });
  });

  it("writes report success only when durable, and never throw", async () => {
    const m = memoryStorage();
    const persistence = createRecoveryPersistence(m.storage);

    assert.equal(await persistence.writeVerifying({ priorUserId: null, recoveryUserId: null }), true);
    m.faults.write = true;
    assert.equal(await persistence.writeVerifying({ priorUserId: "a", recoveryUserId: null }), false);
    assert.equal(await persistence.writeActive("a"), false);
    m.faults.remove = true;
    assert.equal(await persistence.clear(), false);
  });

  it("writes are applied in call order even when issued without awaiting", async () => {
    const m = memoryStorage();
    const persistence = createRecoveryPersistence(m.storage);

    void persistence.writeVerifying({ priorUserId: null, recoveryUserId: null });
    void persistence.writeActive("u-1");
    void persistence.clear();
    await persistence.writeActive("u-2");
    assert.deepEqual(
      m.log.map((entry) => (entry === "remove" ? entry : (JSON.parse(entry.slice(4)) as { phase: string }).phase)),
      ["verifying", "active", "remove", "active"],
    );
    assert.deepEqual(await persistence.read(), { kind: "marker", marker: { v: 1, phase: "active", userId: "u-2" } });
  });

  it("a failed write does not stop the ones behind it", async () => {
    const m = memoryStorage();
    const persistence = createRecoveryPersistence(m.storage);

    m.faults.write = true;
    assert.equal(await persistence.writeActive("u-1"), false);
    m.faults.write = false;
    assert.equal(await persistence.writeActive("u-1"), true);
  });

  it("a verifying write accumulates evidence instead of erasing it", async () => {
    const m = memoryStorage();
    const persistence = createRecoveryPersistence(m.storage);

    await persistence.writeActive("rec-1");
    await persistence.writeVerifying({ priorUserId: null, recoveryUserId: null });
    assert.deepEqual(await persistence.read(), { kind: "marker", marker: { v: 1, phase: "verifying", priorUserId: null, recoveryUserId: "rec-1" } });

    await persistence.writeVerifying({ priorUserId: "prior-1", recoveryUserId: null });
    assert.deepEqual(await persistence.read(), { kind: "marker", marker: { v: 1, phase: "verifying", priorUserId: "prior-1", recoveryUserId: "rec-1" } });

    await persistence.clear();
    await persistence.writeVerifying({ priorUserId: null, recoveryUserId: null });
    assert.deepEqual(await persistence.read(), { kind: "marker", marker: { v: 1, phase: "verifying", priorUserId: null, recoveryUserId: null } }, "nothing carried over from a cleared record");
  });

  it("a verifying write with an unreadable earlier record still writes", async () => {
    const m = memoryStorage({ [RECOVERY_MARKER_KEY]: "{corrupt" });
    const persistence = createRecoveryPersistence(m.storage);

    assert.equal(await persistence.writeVerifying({ priorUserId: "p", recoveryUserId: null }), true);
  });

  it("a record holds user ids only: no token, code, email or URL", async () => {
    const m = memoryStorage();
    const persistence = createRecoveryPersistence(m.storage);

    await persistence.writeVerifying({ priorUserId: "prior-1", recoveryUserId: "rec-1" });

    const stored = [...m.data.values()].join(" ");

    assert.doesNotMatch(stored, /token|code|@|http|valorfinis/i);
  });
});
