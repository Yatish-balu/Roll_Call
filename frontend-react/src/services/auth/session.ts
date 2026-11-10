/**
 * Client-Side Authentication Session Management (React 19 + Axios)
 *
 * Implements:
 * 1. Persistent session storage (sessionStorage for tab lifetime, localStorage when rememberMe is active).
 * 2. Instantaneous restoration on page refresh (F5) without logging out.
 * 3. Automatic in-memory token injection into Axios.
 * 4. Background silent refresh token rotation.
 * 5. Clean session purge on logout.
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

const SESSION_STORAGE_KEY = "rollcall_auth_session";

function loadSavedSession(): AuthSession {
  if (typeof window === "undefined") {
    return {
      token: null,
      role: null,
      userId: null,
      name: null,
      subjectCodes: [],
      expiresAtUtc: null,
    };
  }

  try {
    const raw = sessionStorage.getItem(SESSION_STORAGE_KEY) || localStorage.getItem(SESSION_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as AuthSession;
      if (parsed && parsed.token) {
        // If expired or invalid timestamp, let silentRefresh handle it, but if still valid restore immediately
        if (parsed.expiresAtUtc && new Date(parsed.expiresAtUtc).getTime() > Date.now()) {
          apiClient.setAccessToken(parsed.token);
          return parsed;
        }
      }
    }
  } catch {
    // Ignore corrupt storage
  }

  return {
    token: null,
    role: null,
    userId: null,
    name: null,
    subjectCodes: [],
    expiresAtUtc: null,
  };
}

let currentSession: AuthSession = loadSavedSession();

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

function persistSession(session: AuthSession, rememberMe?: boolean) {
  if (typeof window === "undefined") return;
  try {
    if (session.token) {
      const serialized = JSON.stringify(session);
      sessionStorage.setItem(SESSION_STORAGE_KEY, serialized);
      if (rememberMe) {
        localStorage.setItem(SESSION_STORAGE_KEY, serialized);
      }
    } else {
      sessionStorage.removeItem(SESSION_STORAGE_KEY);
      localStorage.removeItem(SESSION_STORAGE_KEY);
    }
  } catch {
    // Ignore quota errors
  }
}

let initialRefreshAttempted = false;
let initialRefreshPromise: Promise<AuthSession | null> | null = null;

export const silentRefreshOnStartup = async (): Promise<AuthSession | null> => {
  // If we already have a valid in-memory/cached token with more than 2 minutes left, keep it
  if (currentSession.token && currentSession.expiresAtUtc) {
    const remainingMs = new Date(currentSession.expiresAtUtc).getTime() - Date.now();
    if (remainingMs > 2 * 60 * 1000) {
      return getAuthSession();
    }
  }

  if (initialRefreshAttempted && currentSession.token) {
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
          userId: res.name || currentSession.userId,
          name: res.name,
          subjectCodes: res.subject_codes || currentSession.subjectCodes || [],
          expiresAtUtc: res.expires_at_utc,
        };
        persistSession(currentSession);
        notifyListeners();
        return getAuthSession();
      }
    } catch {
      // If refresh fails and existing token is expired, clear
      if (currentSession.expiresAtUtc && new Date(currentSession.expiresAtUtc).getTime() <= Date.now()) {
        apiClient.setAccessToken(null);
        currentSession = {
          token: null,
          role: null,
          userId: null,
          name: null,
          subjectCodes: [],
          expiresAtUtc: null,
        };
        persistSession(currentSession);
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
  persistSession(currentSession, params.rememberMe);
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
    persistSession(currentSession);
    notifyListeners();
  }
};
