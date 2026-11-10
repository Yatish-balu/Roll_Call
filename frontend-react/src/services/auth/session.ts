/**
 * Client-Side Authentication Session Management (React 19 + Axios)
 *
 * Implements:
 * 1. In-memory access token storage (no localStorage/sessionStorage for tokens).
 * 2. Silent refresh on startup using HttpOnly refresh cookies.
 * 3. Logout with server session revocation and cookie clearing.
 * 4. Remember-me parameter propagation.
 */

import { apiClient } from "@/services/api/client";

export interface AuthSession {
  token: string | null;
  role: "ADMIN" | "FACULTY" | "VIEWER" | null;
  userId: string | null;
  name: string | null;
  subjectCodes: string[];
  expiresAtUtc: string | null;
}

let currentSession: AuthSession = {
  token: null,
  role: null,
  userId: null,
  name: null,
  subjectCodes: [],
  expiresAtUtc: null,
};

type AuthListener = (session: AuthSession) => void;
const listeners = new Set<AuthListener>();

export const getAuthSession = (): AuthSession => ({ ...currentSession });

export const subscribeToAuth = (listener: AuthListener): (() => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

const notifyListeners = () => {
  listeners.forEach((listener) => {
    try {
      listener(getAuthSession());
    } catch (e) {
      console.error("Auth listener error:", e);
    }
  });
};

let initialRefreshAttempted = false;
let initialRefreshPromise: Promise<AuthSession | null> | null = null;

export const silentRefreshOnStartup = async (): Promise<AuthSession | null> => {
  if (currentSession.token) {
    return getAuthSession();
  }

  if (initialRefreshAttempted) {
    return getAuthSession();
  }

  if (initialRefreshPromise) {
    return initialRefreshPromise;
  }

  initialRefreshPromise = (async () => {
    initialRefreshAttempted = true;
    try {
      const res = await apiClient.post<{
        token: string;
        role: "ADMIN" | "FACULTY" | "VIEWER";
        name: string;
        subject_codes: string[];
        expires_at_utc: string;
      }>("/api/v1/auth/refresh");

      if (res && res.token) {
        apiClient.setAccessToken(res.token);
        currentSession = {
          token: res.token,
          role: res.role,
          userId: res.name || null,
          name: res.name,
          subjectCodes: res.subject_codes || [],
          expiresAtUtc: res.expires_at_utc,
        };
        notifyListeners();
        return getAuthSession();
      }
    } catch {
      if (!currentSession.token) {
        apiClient.setAccessToken(null);
        currentSession = {
          token: null,
          role: null,
          userId: null,
          name: null,
          subjectCodes: [],
          expiresAtUtc: null,
        };
        notifyListeners();
      }
    } finally {
      initialRefreshPromise = null;
    }
    return getAuthSession();
  })();

  return initialRefreshPromise;
};

export const loginWithPersistentSession = async (params: {
  userId: string;
  password: string;
  adminKey?: string;
  rememberMe?: boolean;
}): Promise<AuthSession> => {
  const res = await apiClient.post<{
    token: string;
    role: "ADMIN" | "FACULTY" | "VIEWER";
    name: string;
    subject_codes: string[];
    expires_at_utc: string;
  }>("/api/v1/auth/login", {
    user_id: params.userId,
    password: params.password,
    admin_key: params.adminKey,
    remember_me: !!params.rememberMe,
  });

  initialRefreshAttempted = true;
  apiClient.setAccessToken(res.token);
  currentSession = {
    token: res.token,
    role: res.role,
    userId: params.userId,
    name: res.name,
    subjectCodes: res.subject_codes || [],
    expiresAtUtc: res.expires_at_utc,
  };
  notifyListeners();
  return getAuthSession();
};

export const logout = async (): Promise<void> => {
  initialRefreshAttempted = false;
  initialRefreshPromise = null;
  try {
    await apiClient.post("/api/v1/auth/logout");
  } catch {
    // Graceful logout
  } finally {
    apiClient.setAccessToken(null);
    currentSession = {
      token: null,
      role: null,
      userId: null,
      name: null,
      subjectCodes: [],
      expiresAtUtc: null,
    };
    notifyListeners();
  }
};

