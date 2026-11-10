import { useCallback, useEffect, useRef } from "react";

// A stable function that is true while the component is mounted. The auth service
// uses it to drop an answer that arrives after the screen was left.
export function useIsMounted(): () => boolean {
  const mounted = useRef(false);

  useEffect(() => {
    mounted.current = true;

    return () => {
      mounted.current = false;
    };
  }, []);

  return useCallback(() => mounted.current, []);
}
