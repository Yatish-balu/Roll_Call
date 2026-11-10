/**
 * Client-Side Authentication Session Management (Wave 1, Prompt N2.1)
 *
 * Implements:
 * 1. In-memory access token storage (no localStorage/sessionStorage).
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

/**
 * Perform silent refresh on application startup using existing HttpOnly cookie.
 * Will only execute if no token exists in memory, and only once on initial boot.
 */
export const silentRefreshOnStartup = async (): Promise<AuthSession | null> => {
  // If a valid in-memory session is already established, preserve it without calling refresh
  if (currentSession.token) {
    return getAuthSession();
  }

  // If initial startup refresh was already attempted, do not repeat
  if (initialRefreshAttempted) {
    return getAuthSession();
  }

  // If a refresh is currently inflight, return the existing promise
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
      // If refresh failed on startup, ensure clean unauthenticated state
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

/**
 * Authenticate credentials, store access token in memory, and receive HttpOnly refresh cookie.
 */
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

  initialRefreshAttempted = true; // Active session established, no startup refresh needed
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

/**
 * Logout and clear session server-side and client-side.
 */
export const logout = async (): Promise<void> => {
  initialRefreshAttempted = false;
  initialRefreshPromise = null;
  try {
    await apiClient.post("/api/v1/auth/logout");
  } catch {
    // Graceful logout even if server unreachable
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
