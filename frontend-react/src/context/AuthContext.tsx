import React, { useEffect, useState, useMemo } from "react";
import {
  type AuthSession,
  getAuthSession,
  loginWithPersistentSession,
  logout as authLogout,
  silentRefreshOnStartup,
  subscribeToAuth,
} from "@/services/auth";
import { AuthContext, type AuthContextValue } from "./auth-context-base";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<AuthSession>(getAuthSession());
  const [isLoading, setIsLoading] = useState<boolean>(() => !getAuthSession().token);

  useEffect(() => {
    const unsubscribe = subscribeToAuth((updated) => {
      setSession(updated);
    });

    if (getAuthSession().token) {
      setIsLoading(false);
      void silentRefreshOnStartup();
      return unsubscribe;
    }

    silentRefreshOnStartup().finally(() => {
      setIsLoading(false);
    });

    return unsubscribe;
  }, []);

  const value = useMemo<AuthContextValue>(() => {
    const isAuthenticated = !!session.token;
    return {
      session,
      isAuthenticated,
      isLoading,
      isAdmin: session.role === "ADMIN",
      isFaculty: session.role === "FACULTY",
      isViewer: session.role === "VIEWER",
      login: loginWithPersistentSession,
      logout: authLogout,
    };
  }, [session, isLoading]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
