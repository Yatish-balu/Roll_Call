"use client";

import { useEffect, useState } from "react";
import {
  type AuthSession,
  getAuthSession,
  loginWithPersistentSession,
  logout,
  silentRefreshOnStartup,
  subscribeToAuth,
} from "@/services/auth";

export function useAuth() {
  const [session, setSession] = useState<AuthSession>(getAuthSession());
  const [isLoading, setIsLoading] = useState<boolean>(() => !getAuthSession().token);

  useEffect(() => {
    // Subscribe to session changes
    const unsubscribe = subscribeToAuth((updated) => {
      setSession(updated);
    });

    // If already authenticated in memory, skip startup refresh
    if (getAuthSession().token) {
      return unsubscribe;
    }

    // Attempt silent refresh once on initial application boot
    silentRefreshOnStartup().finally(() => {
      setIsLoading(false);
    });

    return unsubscribe;
  }, []);

  const isAuthenticated = !!session.token;
  const isAdmin = session.role === "ADMIN";
  const isFaculty = session.role === "FACULTY";
  const isViewer = session.role === "VIEWER";

  return {
    session,
    isAuthenticated,
    isLoading,
    isAdmin,
    isFaculty,
    isViewer,
    login: loginWithPersistentSession,
    logout,
  };
}
