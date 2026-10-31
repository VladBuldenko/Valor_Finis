import {
    createContext,
    ReactNode,
    useContext,
    useEffect,
    useState,
  } from "react";
  import type { Session } from "@supabase/supabase-js";
  
  import { sessionBoundary } from "../../lib/session-runtime";
  import { startAuthSession } from "./auth-session";
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
      () =>
        startAuthSession<Session>({
          auth: supabase.auth,
          boundary: sessionBoundary,
          publish: ({ session: nextSession, isLoading: nextLoading }) => {
            setSession(nextSession);
            setIsLoading(nextLoading);
          },
          onRestoreError: (error) => {
            console.error("Unable to restore Supabase session:", error);
          },
        }),
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