import React, { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { checkBackendHealth } from "@/services/api/health";
import { apiClient } from "@/services/api/client";
import {
  changePassword,
  disableMfa,
  enableMfa,
  fetchActiveSessions,
  fetchMfaStatus,
  revokeAllOtherSessions,
  revokeSession,
  verifyMfa,
  type ActiveSession,
  type MfaStatus,
} from "@/services/api/account";
import {
  applyTheme,
  getPreferences,
  savePreferences,
  type AppPreferences,
  type ThemePreference,
} from "@/lib/preferences";

interface MetaConfig {
  unlimited_attendance_editing: boolean;
  defaulter_threshold_percent: number;
  defaulter_required_percent: number;
  attendance_bands: {
    green_above_percent: number;
    yellow_from_percent: number;
  };
  upload_limits: {
    image_max_bytes: number;
    csv_max_bytes: number;
  };
  access_token_ttl_minutes: number;
  subject_codes: string[];
}

const APP_VERSION = "0.2.0";

function SectionCard({
  title,
  description,
  badge,
  children,
}: {
  title: string;
  description?: string;
  badge?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl shadow-2xs overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 sm:px-6 py-4 border-b border-[#E4DDCA] bg-[#EDE8D8]/25">
        <div>
          <h2 className="text-base font-bold text-[#24251C]">{title}</h2>
          {description && <p className="text-xs text-[#77735F] mt-0.5">{description}</p>}
        </div>
        {badge && (
          <span className="px-2.5 py-1 rounded-lg bg-white border border-[#E4DDCA] text-[10px] font-black uppercase tracking-wider text-[#6C5119]">
            {badge}
          </span>
        )}
      </div>
      <div className="p-5 sm:p-6">{children}</div>
    </section>
  );
}

function Toggle({
  label,
  description,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  description?: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-4 py-3">
      <div className="min-w-0">
        <p className="text-sm font-semibold text-[#24251C]">{label}</p>
        {description && <p className="text-xs text-[#77735F] mt-0.5">{description}</p>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 cursor-pointer ${
          checked ? "bg-[#3F451F]" : "bg-[#E4DDCA]"
        }`}
      >
        <span
          className={`inline-block h-5 w-5 transform rounded-full bg-white transition-transform ${
            checked ? "translate-x-5" : "translate-x-0.5"
          }`}
        />
      </button>
    </div>
  );
}

export function SettingsView() {
  const navigate = useNavigate();
  const { session, logout } = useAuth();

  const [preferences, setPreferences] = useState<AppPreferences>(() => getPreferences());
  const [metaConfig, setMetaConfig] = useState<MetaConfig | null>(null);
  const [health, setHealth] = useState<{ ok: boolean; latencyMs?: number; checkedAt?: string } | null>(
    null
  );
  const [isCheckingHealth, setIsCheckingHealth] = useState(false);

  // Password
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showOldPassword, setShowOldPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [passwordBusy, setPasswordBusy] = useState(false);
  const [passwordMessage, setPasswordMessage] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);

  // MFA
  const [mfaStatus, setMfaStatus] = useState<MfaStatus | null>(null);
  const [mfaPassword, setMfaPassword] = useState("");
  const [showMfaPassword, setShowMfaPassword] = useState(false);
  const [mfaCode, setMfaCode] = useState("");
  const [mfaSecret, setMfaSecret] = useState<string | null>(null);
  const [mfaRecoveryCodes, setMfaRecoveryCodes] = useState<string[]>([]);
  const [mfaBusy, setMfaBusy] = useState(false);
  const [mfaMessage, setMfaMessage] = useState<string | null>(null);
  const [mfaError, setMfaError] = useState<string | null>(null);

  // Sessions
  const [sessions, setSessions] = useState<ActiveSession[]>([]);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [isLoadingSessions, setIsLoadingSessions] = useState(false);
  const [sessionBusyId, setSessionBusyId] = useState<string | null>(null);

  const displayName = session?.name || session?.userId || "Faculty Member";

  const updatePreference = useCallback(<K extends keyof AppPreferences>(
    key: K,
    value: AppPreferences[K]
  ) => {
    setPreferences((prev) => {
      const next = { ...prev, [key]: value };
      savePreferences(next);
      return next;
    });
  }, []);

  useEffect(() => {
    applyTheme(preferences.theme);
  }, [preferences.theme]);

  const checkHealth = useCallback(async () => {
    setIsCheckingHealth(true);
    const started = performance.now();
    try {
      const res = await checkBackendHealth();
      setHealth({
        ok: res.status === "healthy" || res.status === "ok",
        latencyMs: Math.round(performance.now() - started),
        checkedAt: new Date().toLocaleTimeString(),
      });
    } catch {
      setHealth({ ok: false, checkedAt: new Date().toLocaleTimeString() });
    } finally {
      setIsCheckingHealth(false);
    }
  }, []);

  const loadSessions = useCallback(async () => {
    setIsLoadingSessions(true);
    setSessionsError(null);
    try {
      const res = await fetchActiveSessions();
      setSessions(res.sessions || []);
    } catch (err: unknown) {
      setSessionsError(
        err instanceof Error ? err.message : "The active sessions could not be loaded."
      );
    } finally {
      setIsLoadingSessions(false);
    }
  }, []);

  useEffect(() => {
    void checkHealth();
    void loadSessions();
    apiClient
      .get<MetaConfig>("/api/v1/meta/config")
      .then(setMetaConfig)
      .catch(() => setMetaConfig(null));
    fetchMfaStatus()
      .then(setMfaStatus)
      .catch(() => setMfaStatus(null));
  }, [checkHealth, loadSessions]);

  const handlePasswordChange = async (event: React.FormEvent) => {
    event.preventDefault();
    setPasswordMessage(null);
    setPasswordError(null);

    if (newPassword !== confirmPassword) {
      setPasswordError("The new password and its confirmation do not match.");
      return;
    }
    if (newPassword.length < 8) {
      setPasswordError("The new password must be at least 8 characters long.");
      return;
    }

    setPasswordBusy(true);
    try {
      await changePassword({ old_password: oldPassword, new_password: newPassword });
      setPasswordMessage(
        "Password changed. All active sessions were invalidated by the server - please sign in again."
      );
      setOldPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err: unknown) {
      setPasswordError(err instanceof Error ? err.message : "The password could not be changed.");
    } finally {
      setPasswordBusy(false);
    }
  };

  const handleMfaEnable = async () => {
    setMfaBusy(true);
    setMfaMessage(null);
    setMfaError(null);
    try {
      const res = await enableMfa({ current_password: mfaPassword });
      setMfaSecret(res.secret);
      setMfaRecoveryCodes(res.recovery_codes || []);
      setMfaMessage("Scan the secret in your authenticator app, then confirm it with a code.");
    } catch (err: unknown) {
      setMfaError(err instanceof Error ? err.message : "MFA enrollment could not be started.");
    } finally {
      setMfaBusy(false);
    }
  };

  const handleMfaVerify = async () => {
    setMfaBusy(true);
    setMfaMessage(null);
    setMfaError(null);
    try {
      await verifyMfa(mfaCode.trim());
      setMfaSecret(null);
      setMfaRecoveryCodes([]);
      setMfaCode("");
      setMfaPassword("");
      setMfaMessage("Multi-factor authentication is now active for your account.");
      const status = await fetchMfaStatus();
      setMfaStatus(status);
    } catch (err: unknown) {
      setMfaError(err instanceof Error ? err.message : "The MFA code could not be verified.");
    } finally {
      setMfaBusy(false);
    }
  };

  const handleMfaDisable = async () => {
    setMfaBusy(true);
    setMfaMessage(null);
    setMfaError(null);
    try {
      await disableMfa({ current_password: mfaPassword, code: mfaCode.trim() || undefined });
      setMfaPassword("");
      setMfaCode("");
      setMfaMessage("Multi-factor authentication was disabled for your account.");
      const status = await fetchMfaStatus();
      setMfaStatus(status);
    } catch (err: unknown) {
      setMfaError(err instanceof Error ? err.message : "MFA could not be disabled.");
    } finally {
      setMfaBusy(false);
    }
  };

  const handleRevoke = async (sessionId: string) => {
    setSessionBusyId(sessionId);
    setSessionsError(null);
    try {
      await revokeSession(sessionId);
      await loadSessions();
    } catch (err: unknown) {
      setSessionsError(err instanceof Error ? err.message : "The session could not be revoked.");
    } finally {
      setSessionBusyId(null);
    }
  };

  const handleRevokeAll = async () => {
    setSessionBusyId("all");
    setSessionsError(null);
    try {
      await revokeAllOtherSessions();
      await loadSessions();
    } catch (err: unknown) {
      setSessionsError(err instanceof Error ? err.message : "The sessions could not be revoked.");
    } finally {
      setSessionBusyId(null);
    }
  };

  const inputClass =
    "w-full px-3.5 py-2.5 rounded-xl bg-white border border-[#E4DDCA] text-sm text-[#24251C] placeholder-[#77735F]/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119] transition-all";
  const labelClass = "block text-xs font-bold text-[#24251C] mb-1.5";

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <div>
        <h1 className="text-2xl sm:text-3xl font-extrabold text-[#24251C] tracking-tight">
          Settings
        </h1>
        <p className="text-xs sm:text-sm text-[#77735F] mt-1">
          Account, security, sessions and interface preferences. Preferences marked{" "}
          <span className="font-semibold text-[#24251C]">device</span> are stored in this browser
          only - the backend stores the account and security state.
        </p>
      </div>

      {/* Account */}
      <SectionCard title="Account" description="Identity issued by the RollCall AI backend.">
        <div className="flex flex-col sm:flex-row sm:items-center gap-4">
          <div className="w-14 h-14 rounded-2xl bg-[#3F451F] text-[#EDE8D8] flex items-center justify-center font-black text-xl border border-[#E4DDCA]">
            {displayName.charAt(0).toUpperCase()}
          </div>
          <div className="flex-1 grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
            <div>
              <p className="text-[10px] font-black uppercase tracking-wider text-[#77735F]">Name</p>
              <p className="font-semibold text-[#24251C] truncate">{displayName}</p>
            </div>
            <div>
              <p className="text-[10px] font-black uppercase tracking-wider text-[#77735F]">User ID</p>
              <p className="font-mono font-semibold text-[#24251C] truncate">
                {session?.userId || "—"}
              </p>
            </div>
            <div>
              <p className="text-[10px] font-black uppercase tracking-wider text-[#77735F]">Role</p>
              <p className="font-semibold text-[#24251C]">{session?.role || "—"}</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Link
              to="/profile"
              className="px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs font-bold text-[#24251C] hover:bg-[#EDE8D8]/60 transition-colors"
            >
              My profile
            </Link>
            <button
              type="button"
              onClick={async () => {
                await logout();
                navigate("/login");
              }}
              className="px-3.5 py-2 rounded-xl border border-rose-300 text-xs font-bold text-rose-700 hover:bg-rose-50 transition-colors cursor-pointer"
            >
              Sign out
            </button>
          </div>
        </div>
      </SectionCard>

      {/* Password */}
      <SectionCard
        title="Change password"
        description="Server enforced: at least 8 characters with upper case, lower case, a digit and a special character."
      >
        <form onSubmit={handlePasswordChange} className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div>
            <label className={labelClass} htmlFor="oldPassword">
              Current password
            </label>
            <div className="relative">
              <input
                id="oldPassword"
                type={showOldPassword ? "text" : "password"}
                autoComplete="current-password"
                className={`${inputClass} pr-10`}
                value={oldPassword}
                onChange={(e) => setOldPassword(e.target.value)}
                required
              />
              <button
                type="button"
                onClick={() => setShowOldPassword((prev) => !prev)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-[#77735F] hover:text-[#24251C] focus-visible:outline-none focus-visible:text-[#24251C] cursor-pointer p-1"
                aria-label={showOldPassword ? "Hide current password" : "Show current password"}
                title={showOldPassword ? "Hide current password" : "Show current password"}
              >
                {showOldPassword ? (
                  <svg className="w-4 h-4 pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l18 18" />
                  </svg>
                ) : (
                  <svg className="w-4 h-4 pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                  </svg>
                )}
              </button>
            </div>
          </div>
          <div>
            <label className={labelClass} htmlFor="newPassword">
              New password
            </label>
            <div className="relative">
              <input
                id="newPassword"
                type={showNewPassword ? "text" : "password"}
                autoComplete="new-password"
                className={`${inputClass} pr-10`}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
              />
              <button
                type="button"
                onClick={() => setShowNewPassword((prev) => !prev)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-[#77735F] hover:text-[#24251C] focus-visible:outline-none focus-visible:text-[#24251C] cursor-pointer p-1"
                aria-label={showNewPassword ? "Hide new password" : "Show new password"}
                title={showNewPassword ? "Hide new password" : "Show new password"}
              >
                {showNewPassword ? (
                  <svg className="w-4 h-4 pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l18 18" />
                  </svg>
                ) : (
                  <svg className="w-4 h-4 pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                  </svg>
                )}
              </button>
            </div>
          </div>
          <div>
            <label className={labelClass} htmlFor="confirmPassword">
              Confirm new password
            </label>
            <div className="relative">
              <input
                id="confirmPassword"
                type={showConfirmPassword ? "text" : "password"}
                autoComplete="new-password"
                className={`${inputClass} pr-10`}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
              />
              <button
                type="button"
                onClick={() => setShowConfirmPassword((prev) => !prev)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-[#77735F] hover:text-[#24251C] focus-visible:outline-none focus-visible:text-[#24251C] cursor-pointer p-1"
                aria-label={showConfirmPassword ? "Hide confirmed password" : "Show confirmed password"}
                title={showConfirmPassword ? "Hide confirmed password" : "Show confirmed password"}
              >
                {showConfirmPassword ? (
                  <svg className="w-4 h-4 pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l18 18" />
                  </svg>
                ) : (
                  <svg className="w-4 h-4 pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                  </svg>
                )}
              </button>
            </div>
          </div>
          <div className="sm:col-span-3 flex flex-wrap items-center gap-3">
            <button
              type="submit"
              disabled={passwordBusy}
              className="px-4 py-2.5 rounded-xl bg-[#6C5119] hover:bg-[#594214] text-white text-xs font-bold transition-colors disabled:opacity-50 cursor-pointer"
            >
              {passwordBusy ? "Updating…" : "Update password"}
            </button>
            {passwordMessage && (
              <p className="text-xs font-semibold text-emerald-700">{passwordMessage}</p>
            )}
            {passwordError && (
              <p className="text-xs font-semibold text-rose-700">{passwordError}</p>
            )}
          </div>
        </form>
      </SectionCard>

      {/* MFA */}
      <SectionCard
        title="Multi-factor authentication"
        description="TOTP based second factor with single-use recovery codes."
        badge="Server"
      >
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span
              className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-bold border ${
                mfaStatus?.mfa_enabled
                  ? "bg-emerald-50 text-emerald-800 border-emerald-200"
                  : "bg-[#EDE8D8]/40 text-[#77735F] border-[#E4DDCA]"
              }`}
            >
              <span
                className={`w-2 h-2 rounded-full ${
                  mfaStatus?.mfa_enabled ? "bg-emerald-500" : "bg-[#A8A28E]"
                }`}
              />
              {mfaStatus
                ? mfaStatus.mfa_enabled
                  ? "MFA is active"
                  : "MFA is not enabled"
                : "MFA status unavailable"}
            </span>
            {mfaStatus && !mfaStatus.mfa_available && (
              <span className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-2.5 py-1">
                MFA is not configured on this server.
              </span>
            )}
          </div>

          {mfaSecret && (
            <div className="p-4 rounded-xl bg-[#F2EDE0] border border-[#E4DDCA] space-y-3">
              <p className="text-xs font-bold text-[#24251C]">1. Add this secret to your app</p>
              <code className="block p-3 rounded-lg bg-white border border-[#E4DDCA] font-mono text-xs break-all text-[#24251C]">
                {mfaSecret}
              </code>
              {mfaRecoveryCodes.length > 0 && (
                <div>
                  <p className="text-xs font-bold text-[#24251C]">Recovery codes (store them safely)</p>
                  <ul className="mt-1 grid grid-cols-2 sm:grid-cols-3 gap-1.5 font-mono text-[11px] text-[#3F451F]">
                    {mfaRecoveryCodes.map((code) => (
                      <li key={code} className="px-2 py-1 rounded bg-white border border-[#E4DDCA]">
                        {code}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className={labelClass} htmlFor="mfaPassword">
                Current account password
              </label>
              <div className="relative">
                <input
                  id="mfaPassword"
                  type={showMfaPassword ? "text" : "password"}
                  autoComplete="current-password"
                  className={`${inputClass} pr-10`}
                  value={mfaPassword}
                  onChange={(e) => setMfaPassword(e.target.value)}
                />
                <button
                  type="button"
                  onClick={() => setShowMfaPassword((prev) => !prev)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[#77735F] hover:text-[#24251C] focus-visible:outline-none focus-visible:text-[#24251C] cursor-pointer p-1"
                  aria-label={showMfaPassword ? "Hide password" : "Show password"}
                  title={showMfaPassword ? "Hide password" : "Show password"}
                >
                  {showMfaPassword ? (
                    <svg className="w-4 h-4 pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l18 18" />
                    </svg>
                  ) : (
                    <svg className="w-4 h-4 pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                    </svg>
                  )}
                </button>
              </div>
            </div>
            <div>
              <label className={labelClass} htmlFor="mfaCode">
                Authenticator / recovery code
              </label>
              <input
                id="mfaCode"
                className={inputClass}
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value)}
                placeholder="6-digit TOTP code"
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {!mfaStatus?.mfa_enabled && !mfaSecret && (
              <button
                type="button"
                onClick={() => void handleMfaEnable()}
                disabled={mfaBusy || !mfaPassword}
                className="px-4 py-2.5 rounded-xl bg-[#3F451F] text-[#EDE8D8] text-xs font-bold hover:bg-[#343919] transition-colors disabled:opacity-50 cursor-pointer"
              >
                Start MFA enrollment
              </button>
            )}
            {mfaSecret && (
              <button
                type="button"
                onClick={() => void handleMfaVerify()}
                disabled={mfaBusy || !mfaCode.trim()}
                className="px-4 py-2.5 rounded-xl bg-[#6C5119] text-white text-xs font-bold hover:bg-[#594214] transition-colors disabled:opacity-50 cursor-pointer"
              >
                Verify and activate
              </button>
            )}
            {mfaStatus?.mfa_enabled && (
              <button
                type="button"
                onClick={() => void handleMfaDisable()}
                disabled={mfaBusy || !mfaPassword}
                className="px-4 py-2.5 rounded-xl border border-rose-300 text-rose-700 text-xs font-bold hover:bg-rose-50 transition-colors disabled:opacity-50 cursor-pointer"
              >
                Disable MFA
              </button>
            )}
            {mfaMessage && <p className="text-xs font-semibold text-emerald-700">{mfaMessage}</p>}
            {mfaError && <p className="text-xs font-semibold text-rose-700">{mfaError}</p>}
          </div>
        </div>
      </SectionCard>

      {/* Sessions */}
      <SectionCard
        title="Active sessions"
        description="Every device with a valid refresh token. Revoking a session signs that device out."
        badge="Server"
      >
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => void loadSessions()}
              disabled={isLoadingSessions}
              className="px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs font-bold text-[#24251C] hover:bg-[#EDE8D8]/60 transition-colors disabled:opacity-50 cursor-pointer"
            >
              {isLoadingSessions ? "Refreshing…" : "Refresh sessions"}
            </button>
            <button
              type="button"
              onClick={() => void handleRevokeAll()}
              disabled={sessionBusyId === "all"}
              className="px-3.5 py-2 rounded-xl border border-rose-300 text-rose-700 text-xs font-bold hover:bg-rose-50 transition-colors disabled:opacity-50 cursor-pointer"
            >
              Sign out all other devices
            </button>
            {sessionsError && <p className="text-xs font-semibold text-rose-700">{sessionsError}</p>}
          </div>

          {sessions.length === 0 && !isLoadingSessions ? (
            <p className="text-xs text-[#77735F] py-4 text-center bg-[#F2EDE0]/50 rounded-xl border border-dashed border-[#E4DDCA]">
              No active sessions were reported for this account.
            </p>
          ) : (
            <ul className="divide-y divide-[#E4DDCA]/60 border border-[#E4DDCA] rounded-xl overflow-hidden">
              {sessions.map((item) => (
                <li
                  key={item.session_id}
                  className="flex flex-col sm:flex-row sm:items-center gap-3 p-3.5 bg-white"
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-bold text-[#24251C] truncate">
                      {item.user_agent || "Unknown device"}
                    </p>
                    <p className="text-[11px] text-[#77735F] truncate">
                      {item.ip_address || "unknown address"} · created{" "}
                      {item.created_at ? new Date(item.created_at).toLocaleString() : "unknown"}
                    </p>
                    <p className="text-[10px] text-[#77735F] font-mono truncate">{item.session_id}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    {item.revoked_at ? (
                      <span className="px-2 py-1 rounded-lg bg-[#EDE8D8]/50 text-[10px] font-bold text-[#77735F]">
                        Revoked
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => void handleRevoke(item.session_id)}
                        disabled={sessionBusyId === item.session_id}
                        className="px-3 py-1.5 rounded-lg border border-[#E4DDCA] text-[11px] font-bold text-[#24251C] hover:bg-rose-50 hover:text-rose-700 hover:border-rose-300 transition-colors disabled:opacity-50 cursor-pointer"
                      >
                        {sessionBusyId === item.session_id ? "Revoking…" : "Revoke"}
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </SectionCard>

      {/* Appearance */}
      <SectionCard
        title="Appearance"
        description="Interface preferences. These are stored on this device."
        badge="Device"
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {(
            [
              { value: "light", label: "Light", hint: "Clean neutral light surfaces" },
              { value: "dark", label: "Dark", hint: "Reduced glare for night viewing" },
              { value: "system", label: "System", hint: "Sync with OS appearance" },
              { value: "warm", label: "Warm (RollCall)", hint: "Classic cream and olive" },
            ] as const
          ).map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => updatePreference("theme", option.value as ThemePreference)}
              className={`p-4 rounded-xl border text-left transition-all cursor-pointer ${
                preferences.theme === option.value
                  ? "border-[#6C5119] bg-[#EDE8D8]/50 ring-1 ring-[#6C5119] dark:bg-[#2C3022] dark:border-[#D2A847] dark:ring-[#D2A847]"
                  : "border-[#E4DDCA] bg-white hover:border-[#A77A13] dark:bg-[#1A1C15] dark:border-[#2C3022]"
              }`}
            >
              <span className="block text-sm font-bold text-[#24251C] dark:text-[#EDE8D8]">{option.label}</span>
              <span className="block text-[11px] text-[#77735F] dark:text-[#A9AE8C] mt-0.5">{option.hint}</span>
            </button>
          ))}
        </div>
      </SectionCard>

      {/* Sidebar preferences */}
      <SectionCard
        title="Sidebar preferences"
        description="Navigation behaviour. These are stored on this device."
        badge="Device"
      >
        <div className="divide-y divide-[#E4DDCA]/60">
          <Toggle
            label="Collapse the sidebar"
            description="Show a compact icon rail on large screens."
            checked={preferences.sidebarCollapsed}
            onChange={(value) => updatePreference("sidebarCollapsed", value)}
          />
          <Toggle
            label="Compact navigation spacing"
            description="Reduce the vertical padding of the navigation entries."
            checked={preferences.sidebarDensity === "compact"}
            onChange={(value) => updatePreference("sidebarDensity", value ? "compact" : "comfortable")}
          />
        </div>
      </SectionCard>

      {/* Notifications */}
      <SectionCard
        title="Notifications"
        description="The backend does not deliver email notifications yet, so these switches only drive the in-app hints."
        badge="Device"
      >
        <div className="divide-y divide-[#E4DDCA]/60">
          <Toggle
            label="Low attendance warning"
            description="Warn when the attendance of a session drops below the threshold."
            checked={preferences.notificationsLowAttendanceAlert}
            onChange={(value) => updatePreference("notificationsLowAttendanceAlert", value)}
          />
          <Toggle
            label="Session reminders"
            description="Remind me about the classes scheduled for today."
            checked={preferences.notificationsSessionReminders}
            onChange={(value) => updatePreference("notificationsSessionReminders", value)}
          />
          <Toggle
            label="Daily attendance digest"
            description="Prepare an end-of-day summary of my classes."
            checked={preferences.notificationsEmailDigest}
            onChange={(value) => updatePreference("notificationsEmailDigest", value)}
          />
          <div className="flex items-center justify-between gap-4 py-3">
            <div>
              <p className="text-sm font-semibold text-[#24251C]">Warning threshold</p>
              <p className="text-xs text-[#77735F] mt-0.5">
                Used for the in-app warning. The institutional defaulter threshold is{" "}
                {metaConfig ? `${metaConfig.defaulter_threshold_percent}%` : "server defined"}.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <input
                type="number"
                min={50}
                max={95}
                value={preferences.notificationsLowAttendanceThreshold}
                onChange={(e) =>
                  updatePreference("notificationsLowAttendanceThreshold", Number(e.target.value))
                }
                className="w-20 px-3 py-2 rounded-xl bg-white border border-[#E4DDCA] text-sm text-center font-bold"
              />
              <span className="text-xs font-bold text-[#77735F]">%</span>
            </div>
          </div>
        </div>
      </SectionCard>

      {/* Academic preferences */}
      <SectionCard
        title="Academic preferences"
        description="Institute rules are server controlled and shown read-only. Only the roster default is a local preference."
        badge="Mixed"
      >
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm mb-4">
          <div className="p-3.5 rounded-xl bg-white border border-[#E4DDCA]">
            <p className="text-[10px] font-black uppercase tracking-wider text-[#77735F]">
              Defaulter threshold
            </p>
            <p className="text-xl font-black text-[#6C5119]">
              {metaConfig ? `${metaConfig.defaulter_threshold_percent}%` : "—"}
            </p>
          </div>
          <div className="p-3.5 rounded-xl bg-white border border-[#E4DDCA]">
            <p className="text-[10px] font-black uppercase tracking-wider text-[#77735F]">
              Attendance editing
            </p>
            <p className="text-sm font-bold text-[#24251C]">
              {metaConfig
                ? metaConfig.unlimited_attendance_editing
                  ? "Unlimited (server enforced)"
                  : "Restricted (server enforced)"
                : "Server enforced"}
            </p>
          </div>
          <div className="p-3.5 rounded-xl bg-white border border-[#E4DDCA]">
            <p className="text-[10px] font-black uppercase tracking-wider text-[#77735F]">
              Health bands
            </p>
            <p className="text-sm font-bold text-[#24251C]">
              {metaConfig
                ? `Green > ${metaConfig.attendance_bands.green_above_percent}% · Yellow ≥ ${metaConfig.attendance_bands.yellow_from_percent}%`
                : "Server defined"}
            </p>
          </div>
        </div>

        <div className="flex items-center justify-between gap-4 py-2">
          <div>
            <p className="text-sm font-semibold text-[#24251C]">Default roster status</p>
            <p className="text-xs text-[#77735F] mt-0.5">
              The state a student receives when a fresh roster is opened.
            </p>
          </div>
          <select
            value={preferences.academicDefaultRosterStatus}
            onChange={(e) =>
              updatePreference(
                "academicDefaultRosterStatus",
                e.target.value as "UNREVIEWED" | "PRESENT"
              )
            }
            className="px-3 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs font-bold text-[#24251C] cursor-pointer"
          >
            <option value="UNREVIEWED">Unreviewed (manual)</option>
            <option value="PRESENT">Present (mark all)</option>
          </select>
        </div>
      </SectionCard>

      {/* Calendar preferences */}
      <SectionCard
        title="Calendar preferences"
        description="Calendar display options. These are stored on this device."
        badge="Device"
      >
        <div className="divide-y divide-[#E4DDCA]/60">
          <Toggle
            label="Week starts on Monday"
            description="Align the calendar grid with the academic week."
            checked={preferences.calendarWeekStartsMonday}
            onChange={(value) => updatePreference("calendarWeekStartsMonday", value)}
          />
          <Toggle
            label="Show the attendance heatmap"
            description="Colour the calendar cells with the class health band."
            checked={preferences.calendarShowHeatmap}
            onChange={(value) => updatePreference("calendarShowHeatmap", value)}
          />
          <div className="flex items-center justify-between gap-4 py-3">
            <div>
              <p className="text-sm font-semibold text-[#24251C]">Default calendar view</p>
              <p className="text-xs text-[#77735F] mt-0.5">Applied when the calendar is opened.</p>
            </div>
            <select
              value={preferences.calendarDefaultView}
              onChange={(e) =>
                updatePreference("calendarDefaultView", e.target.value as "month" | "week" | "day")
              }
              className="px-3 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs font-bold text-[#24251C] cursor-pointer"
            >
              <option value="month">Month</option>
              <option value="week">Week</option>
              <option value="day">Day</option>
            </select>
          </div>
        </div>
      </SectionCard>

      {/* AI preferences */}
      <SectionCard
        title="AI assistant preferences"
        description="Behaviour of the attendance assistant. Stored on this device."
        badge="Device"
      >
        <div className="divide-y divide-[#E4DDCA]/60">
          <Toggle
            label="Show tool calls"
            description="Display the backend tools the assistant used for every answer."
            checked={preferences.aiShowToolCalls}
            onChange={(value) => updatePreference("aiShowToolCalls", value)}
          />
          <Toggle
            label="Explain extraction confidence"
            description="Show the confidence hint when a scanned record is uncertain."
            checked={preferences.aiExtractionConfidenceHint}
            onChange={(value) => updatePreference("aiExtractionConfidenceHint", value)}
          />
          <Toggle
            label="Auto-confirm high confidence extractions"
            description="The assistant still requires your confirmation before any attendance is written - this only pre-fills the review panel."
            checked={preferences.aiAutoConfirmHighConfidence}
            onChange={(value) => updatePreference("aiAutoConfirmHighConfidence", value)}
          />
        </div>
      </SectionCard>

      {/* Application info */}
      <SectionCard title="Application" description="Build and connectivity information.">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
          <div className="flex items-center justify-between gap-3 p-3.5 rounded-xl bg-white border border-[#E4DDCA]">
            <span className="text-[#77735F]">Version</span>
            <span className="font-mono font-bold text-[#24251C]">v{APP_VERSION}</span>
          </div>
          <div className="flex items-center justify-between gap-3 p-3.5 rounded-xl bg-white border border-[#E4DDCA]">
            <span className="text-[#77735F]">API base</span>
            <span className="font-mono font-bold text-[#24251C]">/api/v1</span>
          </div>
          <div className="flex items-center justify-between gap-3 p-3.5 rounded-xl bg-white border border-[#E4DDCA]">
            <span className="text-[#77735F]">Backend status</span>
            <span
              className={`font-bold inline-flex items-center gap-1.5 ${
                health?.ok ? "text-emerald-700" : "text-rose-700"
              }`}
            >
              <span className={`w-2 h-2 rounded-full ${health?.ok ? "bg-emerald-500" : "bg-rose-500"}`} />
              {health?.ok ? "Operational" : "Unreachable"}
            </span>
          </div>
          <div className="flex items-center justify-between gap-3 p-3.5 rounded-xl bg-white border border-[#E4DDCA]">
            <span className="text-[#77735F]">Latency</span>
            <span className="font-mono font-bold text-[#24251C]">
              {health?.latencyMs !== undefined ? `${health.latencyMs} ms` : "—"}
            </span>
          </div>
        </div>
        <button
          type="button"
          onClick={() => void checkHealth()}
          disabled={isCheckingHealth}
          className="mt-4 px-3.5 py-2 rounded-xl bg-[#3F451F] text-[#EDE8D8] text-xs font-bold hover:bg-[#343919] transition-colors disabled:opacity-50 cursor-pointer"
        >
          {isCheckingHealth ? "Checking…" : "Test server connection"}
        </button>
      </SectionCard>
    </div>
  );
}
