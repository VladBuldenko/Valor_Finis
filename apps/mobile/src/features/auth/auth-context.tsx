import {
    createContext,
    ReactNode,
    useContext,
    useEffect,
    useState,
  } from "react";
  import type { Session } from "@supabase/supabase-js";
  
  import { sessionBoundary } from "../../lib/session-runtime";
  import { createAuthCoordinator } from "./auth-coordinator";
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
  
    useEffect(() => {
      let isMounted = true;

      // Ordering and boundary adoption live in the coordinator (testable
      // without React); this component only mirrors its output.
      const coordinator = createAuthCoordinator<Session>({
        boundary: sessionBoundary,
        publish: ({ session: nextSession, isLoading: nextLoading }) => {
          if (!isMounted) {
            return;
          }

          setSession(nextSession);
          setIsLoading(nextLoading);
        },
      });

      async function loadSession() {
        // Taken before the await: an auth event that arrives meanwhile wins.
        const settle = coordinator.beginInitialRestore();
        const {
          data: { session: initialSession },
          error,
        } = await supabase.auth.getSession();

        if (error) {
          console.error(
            "Unable to restore Supabase session:",
            error,
          );
        }

        settle(initialSession);
      }

      void loadSession();

      // Synchronous on purpose: no Supabase Auth call may be made in here.
      const {
        data: { subscription },
      } = supabase.auth.onAuthStateChange(
        (_event, nextSession) => {
          coordinator.handleAuthEvent(nextSession);
        },
      );

      return () => {
        isMounted = false;
        subscription.unsubscribe();
      };
    }, []);

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