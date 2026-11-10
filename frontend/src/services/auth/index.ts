/**
 * Auth Service Stub (Prepared for Phase 7.2+ Authentication integration)
 */

export interface AuthSession {
  token: string | null;
  role: "ADMIN" | "FACULTY" | "VIEWER" | null;
  userId: string | null;
}

// Authentication will be implemented in subsequent phases.
export const getStoredAuthToken = (): string | null => {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("rollcall_auth_token");
};
