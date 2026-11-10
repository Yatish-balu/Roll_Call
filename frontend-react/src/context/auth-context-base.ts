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
  isAdmin: boolean;
  isFaculty: boolean;
  isViewer: boolean;
  login: typeof loginWithPersistentSession;
  logout: typeof authLogout;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

