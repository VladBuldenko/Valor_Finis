// Fakes for the recovery restart tests (not imported by app code).
import type { KeyValueStorage } from "./recovery-persistence.ts";

export function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  const log: string[] = [];
  const faults = { read: false, write: false, remove: false, failSet: null as ((value: string) => boolean) | null };
  const storage: KeyValueStorage = {
    getItem: async (key) => {
      if (faults.read) throw new Error("read failed");

      return data.get(key) ?? null;
    },
    setItem: async (key, value) => {
      if (faults.write || faults.failSet?.(value)) throw new Error("write failed");

      log.push(`set ${value}`);
      data.set(key, value);
    },
    removeItem: async (key) => {
      if (faults.remove) throw new Error("remove failed");

      log.push("remove");
      data.delete(key);
    },
  };

  return { storage, data, log, faults };
}
