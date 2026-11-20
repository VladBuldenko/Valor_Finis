// True when a single-record read (GET /expenses/{id}, GET /income/{id}) failed
// because the record does not exist for this user. A foreign id and a deleted
// id are the same 404, so the screen says "not found" for both and never shows
// a record that cached data still holds but the server no longer has.
import { isApiError } from "../api/api-error.ts";

export function isRecordNotFound(error: unknown): boolean {
  return isApiError(error) && error.kind === "http" && error.status === 404;
}
