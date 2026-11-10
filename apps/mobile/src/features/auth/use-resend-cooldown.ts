import { useCallback, useEffect, useState } from "react";

import { resendSecondsLeft } from "./auth-registration";

// Seconds until another email may be requested, counting down once per second.
// `start()` marks a send. A cooldown is a courtesy and a guard against double
// sends; the server's own rate limit still applies.
export function useResendCooldown(): { secondsLeft: number; start: () => void } {
  const [sentAt, setSentAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (sentAt === null) {
      return undefined;
    }

    const timer = setInterval(() => setNow(Date.now()), 1000);

    return () => clearInterval(timer);
  }, [sentAt]);

  const start = useCallback(() => {
    const at = Date.now();

    setSentAt(at);
    setNow(at);
  }, []);

  return { secondsLeft: resendSecondsLeft(sentAt, now), start };
}
