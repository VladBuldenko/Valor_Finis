import {
    createContext,
    ReactNode,
    useContext,
    useEffect,
    useState,
  } from "react";
  import type { Session } from "@supabase/supabase-js";
  
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
  
      async function loadSession() {
        const {
          data: { session: initialSession },
          error,
        } = await supabase.auth.getSession();
  
        if (!isMounted) {
          return;
        }
  
        if (error) {
          console.error(
            "Unable to restore Supabase session:",
            error,
          );
        }
  
        setSession(initialSession);
        setIsLoading(false);
      }
  
      void loadSession();
  
      const {
        data: { subscription },
      } = supabase.auth.onAuthStateChange(
        (_event, nextSession) => {
          setSession(nextSession);
          setIsLoading(false);
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