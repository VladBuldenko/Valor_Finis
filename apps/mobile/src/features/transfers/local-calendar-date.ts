// Formats a Date as the device's LOCAL calendar date, YYYY-MM-DD.
// Deliberately built from getFullYear/getMonth/getDate rather than
// toISOString(), which converts to UTC first and can yield the previous or
// next calendar day near midnight outside UTC. This is the user's local
// "today", not the server's (D13 known gap) -- the backend stays the
// authority and rejects a date it considers future.
export function formatLocalCalendarDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");

  return `${year}-${month}-${day}`;
}
