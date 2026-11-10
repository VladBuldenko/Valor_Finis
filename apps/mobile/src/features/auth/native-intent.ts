// The decision made for every incoming URL (see app/+native-intent.ts). Pure.
//
// `receive` is the auth-link handler's claim function: true when the URL is an auth
// link (and the handler now owns its credential). Such a URL is never handed to the
// router: the router only ever sees a harmless path.
export function redirectIncomingUrl(
  receive: (url: string) => boolean,
  event: { path: string; initial: boolean },
): string {
  if (!receive(event.path)) {
    return event.path;
  }

  // Cold start: begin at the root. Already running: an empty path is ignored by the
  // router, so the user stays where they are until the handler decides.
  return event.initial ? "/" : "";
}
