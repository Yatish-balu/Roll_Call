/**
 * Client-Side Authentication Session Management (React 19 + Axios)
 *
 * Security Guarantees:
 * 1. In-memory access token storage ONLY (Never persisted to localStorage or sessionStorage).
 * 2. HttpOnly refresh-cookie architecture for session restoration and rotation.
 * 3. Unified response-application mechanism synchronizing access token, role, subject codes, and expiry.
 * 4. Correct backend userId extraction from signed JWT claims.
 * 5. Strict rejection of failed logins (No client-side role fabrication or demo fallbacks).
 * 6. Automatic session purge and redirect to /login on failed token refresh.
 */

import axios from "axios";
import { apiClient } from "@/services/api/client";

export interface AuthSession {
  token: string | null;
  role: "ADMIN" | "FACULTY" | "VIEWER" | null;
  userId: string | null;
  name: string | null;
  subjectCodes: string[];
  expiresAtUtc: string | null;
}

export interface AuthApiResponse {
  token: string;
  role: "ADMIN" | "FACULTY" | "VIEWER";
  name: string;
  subject_codes?: string[];
  expires_at_utc: string;
}

// In-memory authentication state (Tokens NEVER written to storage)
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
  const snapshot = getAuthSession();
  listeners.forEach((listener) => {
    try {
      listener(snapshot);
    } catch (e) {
      console.error("Auth listener error:", e);
    }
  });
};

/**
 * Extracts the authoritative user_id from the signed JWT access token claims ('sub').
 * Backend issues: {"sub": user.user_id, "role": user.role, ...}
 */
function extractUserIdFromJwt(token: string): string | null {
  try {
    const parts = token.split(".");
    if (parts.length >= 2) {
      const base64Url = parts[1];
      const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
      const jsonPayload = decodeURIComponent(
        atob(base64)
          .split("")
          .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
          .join("")
      );
      const parsed = JSON.parse(jsonPayload);
      if (parsed && typeof parsed.sub === "string") {
        return parsed.sub;
      }
    }
  } catch {
    // Malformed token or non-browser environment
  }
  return null;
}

/**
 * Single shared response-application mechanism.
 * Synchronizes in-memory access token, role, subject codes, expiry, and resolved userId.
 */
export function applyAuthResponse(res: AuthApiResponse, explicitUserId?: string): AuthSession {
  const jwtUserId = extractUserIdFromJwt(res.token);
  const resolvedUserId = jwtUserId || explicitUserId || res.name;

  apiClient.setAccessToken(res.token);

  currentSession = {
    token: res.token,
    role: res.role,
    userId: resolvedUserId,
    name: res.name,
    subjectCodes: res.subject_codes || [],
    expiresAtUtc: res.expires_at_utc,
  };

  notifyListeners();
  return getAuthSession();
}

/**
 * Clears in-memory authentication state and redirects to /login if needed.
 */
export function clearAuthSession(shouldRedirect = false): void {
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

  if (shouldRedirect && typeof window !== "undefined") {
    if (window.location.pathname !== "/login") {
      window.location.href = "/login";
    }
  }
}

// Single-flight refresh promise to prevent concurrent duplicate refresh requests
let refreshInFlight: Promise<string | null> | null = null;

/**
 * Executes a refresh request against the backend using HttpOnly cookie credentials.
 * Used by both startup initialization and Axios 401 interceptor.
 */
export const performAuthRefresh = async (): Promise<string | null> => {
  if (refreshInFlight) {
    return refreshInFlight;
  }

  refreshInFlight = (async () => {
    try {
      const res = await axios.post<AuthApiResponse>(
        `${apiClient.getEffectiveBaseUrl()}/api/v1/auth/refresh`,
        {},
        {
          withCredentials: true,
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json",
            "X-Requested-With": "XMLHttpRequest",
          },
        }
      );

      if (res.data && res.data.token) {
        applyAuthResponse(res.data);
        return res.data.token;
      }

      clearAuthSession(true);
      return null;
    } catch {
      clearAuthSession(true);
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
};

// Register the shared refresh handler with ApiClient for automated 401 recovery
apiClient.setRefreshHandler(performAuthRefresh);

/**
 * Invoked on startup to restore session from HttpOnly cookie if present.
 */
export const silentRefreshOnStartup = async (): Promise<AuthSession | null> => {
  // If we already have a valid in-memory token with > 2 mins remaining, keep it
  if (currentSession.token && currentSession.expiresAtUtc) {
    const remainingMs = new Date(currentSession.expiresAtUtc).getTime() - Date.now();
    if (remainingMs > 2 * 60 * 1000) {
      return getAuthSession();
    }
  }

  const token = await performAuthRefresh();
  if (token) {
    return getAuthSession();
  }

  // If startup refresh fails, clear in-memory state without forced redirect loop
  clearAuthSession(false);
  return null;
};

/**
 * Authenticates user credentials with the backend API.
 * Never fabricates sessions, never suppresses backend authentication errors.
 */
export const loginWithPersistentSession = async (params: {
  userId: string;
  password: string;
  adminKey?: string;
  rememberMe?: boolean;
}): Promise<AuthSession> => {
  const res = await apiClient.post<AuthApiResponse>("/api/v1/auth/login", {
    user_id: params.userId.trim(),
    password: params.password,
    admin_key: params.adminKey?.trim() || undefined,
    remember_me: !!params.rememberMe,
  });

  return applyAuthResponse(res, params.userId.trim());
};

/**
 * Revokes current session on backend and clears in-memory auth state.
 */
export const logout = async (): Promise<void> => {
  try {
    await apiClient.post("/api/v1/auth/logout");
  } catch {
    // Graceful logout even if backend unreachable
  } finally {
    clearAuthSession(true);
  }
};
