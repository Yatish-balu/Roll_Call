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
    const role = session.role;
    const isAdmin = role === "ADMIN";
    const isStrictFaculty = role === "FACULTY";
    const isFaculty = isAdmin || isStrictFaculty; // ADMIN inherits FACULTY capabilities
    const isViewer = role === "VIEWER";

    // Centralized capability helpers (matching backend role hierarchy: ADMIN > FACULTY > VIEWER)
    const canView = isAuthenticated;
    const canWrite = isAdmin || isStrictFaculty;
    const canMarkAttendance = isAdmin || isStrictFaculty;
    const canManageStudents = isAdmin;
    const canManageFaculty = isAdmin;
    const canManageRooms = isAdmin;
    const canScheduleSessions = isAdmin || isStrictFaculty;

    return {
      session,
      isAuthenticated,
      isLoading,
      isAdmin,
      isFaculty,
      isStrictFaculty,
      isViewer,
      canView,
      canWrite,
      canMarkAttendance,
      canManageStudents,
      canManageFaculty,
      canManageRooms,
      canScheduleSessions,
      login: loginWithPersistentSession,
      logout: authLogout,
    };
  }, [session, isLoading]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
