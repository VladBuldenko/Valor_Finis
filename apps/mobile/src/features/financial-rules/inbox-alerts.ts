// Paging for the Alerts screen (VF-020F4): manual "Load more" driven only by
// the backend's metadata. Pure and Node-testable.
import type { RuleAlertList } from "./financial-rule.types.ts";

export const ALERTS_PAGE_SIZE = 20;

// The offset of the next page, or undefined when the metadata says everything
// was received (or the alerts schema is unavailable / the page was empty).
export function nextAlertOffset(last: RuleAlertList, loadedCount: number): number | undefined {
  if (last.available === false || last.items.length === 0) {
    return undefined;
  }

  return loadedCount < last.total ? loadedCount : undefined;
}
