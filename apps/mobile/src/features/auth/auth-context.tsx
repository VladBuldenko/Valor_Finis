import {
    createContext,
    ReactNode,
    useContext,
    useEffect,
    useState,
    useSyncExternalStore,
  } from "react";
  import type { Session } from "@supabase/supabase-js";
  
  import { onSettledAuthState, recoveryState } from "../../lib/auth-link-runtime";
  import { sessionBoundary } from "../../lib/session-runtime";
  import { startAuthSession } from "./auth-session";
  import { decideRootRoute, type RootRoute } from "./recovery-state";
  import { supabase } from "../../lib/supabase";
  
  type AuthContextValue = {
    session: Session | null;
    isLoading: boolean;
  };
  
  const AuthContext = createContext<AuthContextValue | undefined>(
    undefined,
  );
  
  type AuthProviderProps = {
    children: ReactNode;
  };
  
  export function AuthProvider({
    children,
  }: AuthProviderProps) {
    const [session, setSession] = useState<Session | null>(
      null,
    );
    const [isLoading, setIsLoading] = useState(true);
  
    useEffect(
      // All lifecycle rules (restore vs. events, disposal, boundary authority)
      // live in startAuthSession / the coordinator; this only mirrors state.
      () => {
        // The stored session could not be read (offline, storage): "no session" then
        // only means "not loaded yet" (see recovery-startup.ts).
        let restoreFailed = false;

        return startAuthSession<Session>({
          auth: supabase.auth,
          boundary: sessionBoundary,
          publish: ({ session: nextSession, isLoading: nextLoading }) => {
            // A password recovery belongs to one user: any other user (or nobody)
            // ends it, so it can never carry over to a different account.
            recoveryState.reconcile(nextSession?.user.id ?? null);

            // The first settled state: decide what a recovery that was in progress when
            // the process ended means for the restored session. The state stays closed
            // ("resolving") until that is done.
            if (!nextLoading) {
              onSettledAuthState(nextSession?.user.id ?? null, restoreFailed);
            }

            setSession(nextSession);
            setIsLoading(nextLoading);
          },
          onRestoreError: (error) => {
            restoreFailed = true;
            console.error("Unable to restore Supabase session:", error);
          },
        });
      },
      [],
    );

    return (
      <AuthContext.Provider
        value={{
          session,
          isLoading,
        }}
      >
        {children}
      </AuthContext.Provider>
    );
  }
  
  export function useAuth() {
    const context = useContext(AuthContext);
  
    if (!context) {
      throw new Error(
        "useAuth must be used inside AuthProvider.",
      );
    }
  
    return context;
  }

  // Where the root navigator should be (see recovery-state.ts). While a password
  // recovery is in progress the session is NOT an app session: data screens stay
  // unmounted until the new password is set.
  export function useRootRoute(): { route: RootRoute; userId: string | null } {
    const { session, isLoading } = useAuth();
    const recovery = useSyncExternalStore(
      recoveryState.subscribe,
      recoveryState.getSnapshot,
      recoveryState.getSnapshot,
    );
    const userId = session?.user.id ?? null;

    return { route: decideRootRoute({ isLoading, userId, recovery }), userId };
  }

  // The recovery state, for hosts that must wait for the startup resolution.
  export function useRecoverySnapshot() {
    return useSyncExternalStore(recoveryState.subscribe, recoveryState.getSnapshot, recoveryState.getSnapshot);
  }

  // The user whose data the app may load, or null (signed out, or recovering).
  export function useAppUserId(): string | null {
    const { route, userId } = useRootRoute();

    return route === "app" ? userId : null;
  }
