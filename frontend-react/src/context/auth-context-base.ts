import { createContext } from "react";
import {
  type AuthSession,
  loginWithPersistentSession,
  logout as authLogout,
} from "@/services/auth";

export interface AuthContextValue {
  session: AuthSession;
  isAuthenticated: boolean;
  isLoading: boolean;
  // Role flags (hierarchy-aware)
  isAdmin: boolean;
  isFaculty: boolean;
  isStrictFaculty: boolean;
  isViewer: boolean;
  // Centralized capability helpers
  canView: boolean;
  canWrite: boolean;
  canMarkAttendance: boolean;
  canManageStudents: boolean;
  canManageFaculty: boolean;
  canManageRooms: boolean;
  canScheduleSessions: boolean;
  login: typeof loginWithPersistentSession;
  logout: typeof authLogout;
}

export const AuthContext = createContext<AuthContextValue | null>(null);
