// The durable record of a password recovery, so that it survives the process being
// killed. Pure and Node-testable (the storage is injected; the app uses AsyncStorage).
//
// WHY. A recovery link creates a real Supabase session that auth-js persists. If the
// app is killed before the new password is set, that session is restored on the next
// start and would open the data screens. The in-memory recovery state is gone, so the
// "this session is only a recovery session" fact must be durable too.
//
// WHAT IS STORED. Never a token, a code or an email: only a phase and user ids.
//   { phase: "verifying", priorUserId, recoveryUserId }  written BEFORE a link code is
//        exchanged. priorUserId: who was signed in then; recoveryUserId: whose recovery
//        was already in force. If the process dies anywhere after the exchange started,
//        this is what remains, and startup treats an unexplained new session as
//        unresolved (fail closed, recovery-startup.ts).
//   { phase: "active", userId }                           the recovery session of userId
//        is the current session and the password has not been set.
// No record means "no recovery in progress".
//
// ORDER IS THE SAFETY ARGUMENT
//  * The verifying record is written (and must succeed) before the exchange; if it
//    cannot be written the exchange is not attempted.
//  * It is removed only after the recovery has ended (password set, or the session
//    signed out), never before: a crash in between leaves a record without a session,
//    which startup clears, instead of a session without a record.
// Writes are serialized, so the last state change wins, in call order.

export type RecoveryMarker =
  | { v: 1; phase: "verifying"; priorUserId: string | null; recoveryUserId: string | null }
  | { v: 1; phase: "active"; userId: string };

export type MarkerRead =
  | { kind: "none" }
  | { kind: "marker"; marker: RecoveryMarker }
  // Present but not understood, or the storage failed: unresolved, treated as unsafe.
  | { kind: "unreadable" };

export type KeyValueStorage = {
  getItem: (key: string) => Promise<string | null>;
  setItem: (key: string, value: string) => Promise<void>;
  removeItem: (key: string) => Promise<void>;
};

export const RECOVERY_MARKER_KEY = "valorfinis.password-recovery.v1";

const USER_ID = /^[A-Za-z0-9-]{1,64}$/;
const isUserId = (value: unknown): value is string => typeof value === "string" && USER_ID.test(value);
const isOptionalUserId = (value: unknown): value is string | null => value === null || isUserId(value);

export function parseMarker(raw: string): RecoveryMarker | null {
  let value: unknown;

  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }

  if (typeof value !== "object" || value === null) {
    return null;
  }

  const record = value as Record<string, unknown>;

  if (record.v !== 1) {
    return null;
  }

  if (record.phase === "active" && isUserId(record.userId)) {
    return { v: 1, phase: "active", userId: record.userId };
  }

  if (record.phase === "verifying" && isOptionalUserId(record.priorUserId) && isOptionalUserId(record.recoveryUserId)) {
    return { v: 1, phase: "verifying", priorUserId: record.priorUserId, recoveryUserId: record.recoveryUserId };
  }

  return null;
}

export function createRecoveryPersistence(storage: KeyValueStorage, key: string = RECOVERY_MARKER_KEY) {
  let tail: Promise<unknown> = Promise.resolve();

  // Serialized, and never throws: the caller learns only whether it worked.
  function enqueue(operation: () => Promise<void>): Promise<boolean> {
    const result = tail.then(operation).then(
      () => true,
      () => false,
    );

    tail = result;

    return result;
  }

  return {
    async read(): Promise<MarkerRead> {
      await tail;

      let raw: string | null;

      try {
        raw = await storage.getItem(key);
      } catch {
        return { kind: "unreadable" };
      }

      if (raw === null) {
        return { kind: "none" };
      }

      const marker = parseMarker(raw);

      return marker ? { kind: "marker", marker } : { kind: "unreadable" };
    },

    // Resolves true only when the record is durably written. Evidence is only ever
    // ACCUMULATED: an earlier record (an active recovery, or a verifying one that startup
    // deferred) contributes its user ids, so starting another exchange can never erase
    // the fact that a recovery session may still be waiting to load.
    writeVerifying(context: { priorUserId: string | null; recoveryUserId: string | null }): Promise<boolean> {
      return enqueue(async () => {
        let earlier: RecoveryMarker | null = null;

        try {
          const raw = await storage.getItem(key);

          earlier = raw === null ? null : parseMarker(raw);
        } catch {
          earlier = null;
        }

        const earlierRecovery = earlier === null ? null : earlier.phase === "active" ? earlier.userId : earlier.recoveryUserId;
        const earlierPrior = earlier !== null && earlier.phase === "verifying" ? earlier.priorUserId : null;
        const marker: RecoveryMarker = {
          v: 1,
          phase: "verifying",
          priorUserId: context.priorUserId ?? earlierPrior,
          recoveryUserId: context.recoveryUserId ?? earlierRecovery,
        };

        await storage.setItem(key, JSON.stringify(marker));
      });
    },

    writeActive(userId: string): Promise<boolean> {
      const marker: RecoveryMarker = { v: 1, phase: "active", userId };

      return enqueue(() => storage.setItem(key, JSON.stringify(marker)));
    },

    clear(): Promise<boolean> {
      return enqueue(() => storage.removeItem(key));
    },
  };
}

export type RecoveryPersistence = ReturnType<typeof createRecoveryPersistence>;
