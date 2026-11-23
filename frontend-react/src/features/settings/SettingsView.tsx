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
  requestRevokeAllSessionsOtp,
  revokeAllOtherSessions,
  revokeSession,
  verifyMfa,
  type ActiveSession,
  type MfaStatus,
  type RevokeAllOtpResult,
} from "@/services/api/account";
import QRCode from "qrcode";
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
  const [passwordBusy, setPasswordBusy] = useState(false);
  const [passwordMessage, setPasswordMessage] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);

  // MFA
  const [mfaStatus, setMfaStatus] = useState<MfaStatus | null>(null);
  const [mfaPassword, setMfaPassword] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [mfaSecret, setMfaSecret] = useState<string | null>(null);
  const [mfaRecoveryCodes, setMfaRecoveryCodes] = useState<string[]>([]);
  const [mfaBusy, setMfaBusy] = useState(false);
  const [mfaMessage, setMfaMessage] = useState<string | null>(null);
  const [mfaError, setMfaError] = useState<string | null>(null);
  const [qrCodeDataUrl, setQrCodeDataUrl] = useState<string | null>(null);
  const [copiedSecret, setCopiedSecret] = useState(false);
  const [copiedRecovery, setCopiedRecovery] = useState(false);
  const [isEnrollmentOpen, setIsEnrollmentOpen] = useState(false);
  const [isDisableOpen, setIsDisableOpen] = useState(false);

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
      setIsDisableOpen(false);
      setMfaMessage("Multi-factor authentication was disabled for your account.");
      const status = await fetchMfaStatus();
      setMfaStatus(status);
    } catch (err: unknown) {
      setMfaError(err instanceof Error ? err.message : "MFA could not be disabled.");
    } finally {
      setMfaBusy(false);
    }
  };

  useEffect(() => {
    if (mfaSecret && session?.userId) {
      const userLabel = encodeURIComponent(session.userId);
      const issuer = encodeURIComponent("RollCall AI");
      const uri = `otpauth://totp/${issuer}:${userLabel}?secret=${mfaSecret}&issuer=${issuer}`;
      QRCode.toDataURL(uri, {
        width: 200,
        margin: 2,
        color: {
          dark: "#24251C",
          light: "#FFFFFF",
        },
      })
        .then((url: string) => setQrCodeDataUrl(url))
        .catch(() => setQrCodeDataUrl(null));
    } else {
      setQrCodeDataUrl(null);
    }
  }, [mfaSecret, session?.userId]);

  const handleCopySecret = async () => {
    if (!mfaSecret) return;
    try {
      await navigator.clipboard.writeText(mfaSecret);
      setCopiedSecret(true);
      setTimeout(() => setCopiedSecret(false), 2000);
    } catch {
      // fallback
    }
  };

  const handleCopyRecoveryCodes = async () => {
    if (mfaRecoveryCodes.length === 0) return;
    try {
      await navigator.clipboard.writeText(mfaRecoveryCodes.join("\n"));
      setCopiedRecovery(true);
      setTimeout(() => setCopiedRecovery(false), 2000);
    } catch {
      // fallback
    }
  };

  const handleDownloadRecoveryCodes = () => {
    if (mfaRecoveryCodes.length === 0) return;
    const content = `RollCall AI - MFA Emergency Recovery Codes\nUser: ${session?.userId || "faculty"}\nGenerated: ${new Date().toISOString()}\n\nKeep these codes safe. Each code can be used once if you lose access to your authenticator app:\n\n${mfaRecoveryCodes.join("\n")}\n`;
    const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `rollcall-mfa-recovery-codes-${session?.userId || "user"}.txt`;
    a.click();
    URL.revokeObjectURL(url);
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

  const [isRevokeModalOpen, setIsRevokeModalOpen] = useState(false);
  const [isRequestingOtp, setIsRequestingOtp] = useState(false);
  const [isSubmittingRevoke, setIsSubmittingRevoke] = useState(false);
  const [revokeOtpData, setRevokeOtpData] = useState<RevokeAllOtpResult | null>(null);
  const [revokeOtpCode, setRevokeOtpCode] = useState("");
  const [revokeModalError, setRevokeModalError] = useState<string | null>(null);
  const [revokeSuccessMessage, setRevokeSuccessMessage] = useState<string | null>(null);

  const handleOpenRevokeModal = async () => {
    setIsRevokeModalOpen(true);
    setIsRequestingOtp(true);
    setRevokeModalError(null);
    setRevokeOtpCode("");
    setRevokeSuccessMessage(null);
    try {
      const res = await requestRevokeAllSessionsOtp();
      setRevokeOtpData(res);
    } catch (err: unknown) {
      setRevokeModalError(
        err instanceof Error ? err.message : "Failed to deliver security verification OTP."
      );
    } finally {
      setIsRequestingOtp(false);
    }
  };

  const handleResendOtp = async () => {
    setIsRequestingOtp(true);
    setRevokeModalError(null);
    try {
      const res = await requestRevokeAllSessionsOtp();
      setRevokeOtpData(res);
    } catch (err: unknown) {
      setRevokeModalError(
        err instanceof Error ? err.message : "Failed to resend verification OTP."
      );
    } finally {
      setIsRequestingOtp(false);
    }
  };

  const handleConfirmRevokeAll = async () => {
    if (!revokeOtpCode.trim()) {
      setRevokeModalError("Please enter the 6-digit confirmation code.");
      return;
    }
    setIsSubmittingRevoke(true);
    setRevokeModalError(null);
    try {
      await revokeAllOtherSessions(revokeOtpCode.trim());
      setIsRevokeModalOpen(false);
      setRevokeOtpCode("");
      setRevokeSuccessMessage("All other device sessions have been securely signed out.");
      await loadSessions();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Verification failed. The code may be incorrect or expired.";
      setRevokeModalError(msg);
    } finally {
      setIsSubmittingRevoke(false);
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
            <input
              id="oldPassword"
              type="password"
              autoComplete="current-password"
              className={inputClass}
              value={oldPassword}
              onChange={(e) => setOldPassword(e.target.value)}
              required
            />
          </div>
          <div>
            <label className={labelClass} htmlFor="newPassword">
              New password
            </label>
            <input
              id="newPassword"
              type="password"
              autoComplete="new-password"
              className={inputClass}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
            />
          </div>
          <div>
            <label className={labelClass} htmlFor="confirmPassword">
              Confirm new password
            </label>
            <input
              id="confirmPassword"
              type="password"
              autoComplete="new-password"
              className={inputClass}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
            />
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
        title="Two-Factor Authentication (2FA)"
        description="Time-based one-time passwords (TOTP) and single-use emergency recovery codes."
        badge="Security"
      >
        <div className="space-y-5">
          {/* Status Indicator */}
          <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-[#E4DDCA]/60">
            <div className="flex items-center space-x-2.5">
              <span
                className={`w-3 h-3 rounded-full ${
                  mfaStatus?.mfa_enabled ? "bg-emerald-500 animate-pulse" : "bg-[#A8A28E]"
                }`}
              />
              <span className="font-bold text-sm text-[#24251C]">
                {mfaStatus?.mfa_enabled ? "2FA Protection Active" : "2FA Protection Inactive"}
              </span>
            </div>
            <span
              className={`px-3 py-1 rounded-xl text-xs font-black uppercase tracking-wider border ${
                mfaStatus?.mfa_enabled
                  ? "bg-emerald-50 text-emerald-800 border-emerald-200"
                  : "bg-[#EDE8D8]/50 text-[#77735F] border-[#E4DDCA]"
              }`}
            >
              {mfaStatus?.mfa_enabled ? "Enabled" : "Disabled"}
            </span>
          </div>

          {/* Messages */}
          {mfaMessage && (
            <div className="p-3 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs font-semibold flex items-center space-x-2">
              <span>✅</span>
              <span>{mfaMessage}</span>
            </div>
          )}
          {mfaError && (
            <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 text-xs font-semibold flex items-center space-x-2">
              <span>⚠️</span>
              <span>{mfaError}</span>
            </div>
          )}

          {/* Case 1: MFA is Active */}
          {mfaStatus?.mfa_enabled && !mfaSecret && (
            <div className="space-y-4">
              <div className="p-4 rounded-xl bg-emerald-50/70 border border-emerald-200 space-y-2">
                <div className="flex items-center space-x-2 text-emerald-900 font-bold text-sm">
                  <span>🛡️</span>
                  <span>Your account is secured with Two-Factor Authentication</span>
                </div>
                <p className="text-xs text-emerald-800 leading-relaxed">
                  Every sign-in requires your password plus a live 6-digit authenticator code.
                  If you need to change your authenticator device or rotate recovery codes, you can re-enroll below.
                </p>
              </div>

              {!isDisableOpen ? (
                <div className="flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    onClick={() => {
                      setIsEnrollmentOpen(true);
                      setMfaPassword("");
                    }}
                    className="px-4 py-2.5 rounded-xl bg-[#3F451F] text-[#EDE8D8] text-xs font-bold hover:bg-[#343919] transition-colors cursor-pointer"
                  >
                    🔄 Reconfigure / Re-enroll 2FA
                  </button>
                  <button
                    type="button"
                    onClick={() => setIsDisableOpen(true)}
                    className="px-4 py-2.5 rounded-xl border border-rose-300 text-rose-700 text-xs font-bold hover:bg-rose-50 transition-colors cursor-pointer"
                  >
                    Disable 2FA
                  </button>
                </div>
              ) : (
                <div className="p-4 rounded-xl bg-rose-50 border border-rose-200 space-y-3">
                  <h4 className="text-xs font-bold text-rose-900">
                    Confirm disabling Two-Factor Authentication
                  </h4>
                  <p className="text-xs text-rose-700">
                    Enter your account password to confirm disabling 2FA. This will lower your account security.
                  </p>
                  <div className="flex flex-col sm:flex-row gap-3">
                    <input
                      type="password"
                      placeholder="Account password"
                      value={mfaPassword}
                      onChange={(e) => setMfaPassword(e.target.value)}
                      className={inputClass}
                    />
                    <div className="flex items-center space-x-2 shrink-0">
                      <button
                        type="button"
                        onClick={() => void handleMfaDisable()}
                        disabled={mfaBusy || !mfaPassword}
                        className="px-4 py-2.5 rounded-xl bg-rose-600 text-white text-xs font-bold hover:bg-rose-700 transition-colors disabled:opacity-50 cursor-pointer"
                      >
                        {mfaBusy ? "Disabling…" : "Confirm Disable"}
                      </button>
                      <button
                        type="button"
                        onClick={() => setIsDisableOpen(false)}
                        className="px-3.5 py-2.5 rounded-xl bg-[#EDE8D8] text-[#24251C] text-xs font-semibold hover:bg-[#E4DDCA] transition-colors cursor-pointer"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Case 2: Enrollment In Progress (Secret is present) */}
          {mfaSecret && (
            <div className="space-y-6 p-5 rounded-2xl bg-[#F2EDE0]/60 border border-[#E4DDCA]">
              <div className="border-b border-[#E4DDCA] pb-3">
                <h3 className="text-sm font-bold text-[#24251C] flex items-center space-x-2">
                  <span>📱</span>
                  <span>Two-Factor Authentication Setup</span>
                </h3>
                <p className="text-xs text-[#77735F] mt-0.5">
                  Complete these 3 steps to activate two-factor authentication on your account.
                </p>
              </div>

              {/* Step 1: Scan QR Code & Secret */}
              <div className="space-y-3">
                <div className="flex items-center space-x-2">
                  <span className="w-5 h-5 rounded-full bg-[#3F451F] text-[#EDE8D8] text-[11px] font-black flex items-center justify-center">
                    1
                  </span>
                  <h4 className="text-xs font-bold text-[#24251C]">
                    Scan QR Code or Enter Secret Key
                  </h4>
                </div>
                <p className="text-xs text-[#77735F]">
                  Open Google Authenticator, Microsoft Authenticator, Authy, or 1Password, and scan the QR code below:
                </p>

                <div className="flex flex-col sm:flex-row items-center sm:items-start gap-5 pt-2">
                  {qrCodeDataUrl ? (
                    <div className="p-3 bg-white rounded-2xl border border-[#E4DDCA] shadow-2xs shrink-0">
                      <img
                        src={qrCodeDataUrl}
                        alt="2FA QR Code"
                        className="w-44 h-44 object-contain"
                      />
                    </div>
                  ) : (
                    <div className="w-44 h-44 rounded-2xl bg-white border border-[#E4DDCA] flex items-center justify-center text-xs text-[#77735F]">
                      Generating QR…
                    </div>
                  )}

                  <div className="space-y-3 flex-1 min-w-0">
                    <div>
                      <span className="text-[11px] font-bold text-[#77735F] uppercase tracking-wider block mb-1">
                        Manual Entry Key (Base32)
                      </span>
                      <div className="flex items-center space-x-2">
                        <code className="flex-1 p-2.5 rounded-xl bg-white border border-[#E4DDCA] font-mono text-xs text-[#24251C] break-all select-all font-bold">
                          {mfaSecret}
                        </code>
                        <button
                          type="button"
                          onClick={() => void handleCopySecret()}
                          className="px-3 py-2.5 rounded-xl bg-[#EDE8D8] text-[#24251C] text-xs font-bold hover:bg-[#E4DDCA] transition-colors shrink-0 cursor-pointer"
                        >
                          {copiedSecret ? "✓ Copied" : "📋 Copy"}
                        </button>
                      </div>
                    </div>

                    {session?.userId && (
                      <a
                        href={`otpauth://totp/RollCall%20AI:${encodeURIComponent(session.userId)}?secret=${mfaSecret}&issuer=RollCall%20AI`}
                        className="inline-flex items-center space-x-1.5 text-xs font-bold text-[#6C5119] hover:underline"
                      >
                        <span>📲 Open Directly in Authenticator App</span>
                        <span>↗</span>
                      </a>
                    )}
                  </div>
                </div>
              </div>

              {/* Step 2: Emergency Recovery Codes */}
              {mfaRecoveryCodes.length > 0 && (
                <div className="space-y-3 pt-3 border-t border-[#E4DDCA]">
                  <div className="flex items-center justify-between flex-wrap gap-2">
                    <div className="flex items-center space-x-2">
                      <span className="w-5 h-5 rounded-full bg-[#3F451F] text-[#EDE8D8] text-[11px] font-black flex items-center justify-center">
                        2
                      </span>
                      <h4 className="text-xs font-bold text-[#24251C]">
                        Save Emergency Recovery Codes
                      </h4>
                    </div>
                    <div className="flex items-center space-x-2">
                      <button
                        type="button"
                        onClick={() => void handleCopyRecoveryCodes()}
                        className="px-2.5 py-1 rounded-lg bg-white border border-[#E4DDCA] text-xs font-bold text-[#24251C] hover:bg-[#EDE8D8] transition-colors cursor-pointer"
                      >
                        {copiedRecovery ? "✓ Codes Copied" : "📋 Copy All Codes"}
                      </button>
                      <button
                        type="button"
                        onClick={handleDownloadRecoveryCodes}
                        className="px-2.5 py-1 rounded-lg bg-[#3F451F] text-[#EDE8D8] text-xs font-bold hover:bg-[#343919] transition-colors cursor-pointer"
                      >
                        💾 Download .txt
                      </button>
                    </div>
                  </div>

                  <p className="text-xs text-[#77735F]">
                    Save these backup codes. If you ever lose access to your phone or authenticator app, each code can be used once to log in.
                  </p>

                  <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 pt-1">
                    {mfaRecoveryCodes.map((code, idx) => (
                      <div
                        key={code}
                        className="p-2 rounded-xl bg-white border border-[#E4DDCA] text-center font-mono text-xs font-bold text-[#3F451F]"
                      >
                        <span className="text-[10px] text-[#A8A28E] block">{idx + 1}</span>
                        {code}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Step 3: Verify and Activate */}
              <div className="space-y-3 pt-3 border-t border-[#E4DDCA]">
                <div className="flex items-center space-x-2">
                  <span className="w-5 h-5 rounded-full bg-[#3F451F] text-[#EDE8D8] text-[11px] font-black flex items-center justify-center">
                    3
                  </span>
                  <h4 className="text-xs font-bold text-[#24251C]">
                    Enter the 6-Digit Code from Authenticator
                  </h4>
                </div>

                <div className="flex flex-col sm:flex-row items-center gap-3">
                  <input
                    type="text"
                    inputMode="numeric"
                    pattern="[0-9]*"
                    maxLength={6}
                    placeholder="000000"
                    value={mfaCode}
                    onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, ""))}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && mfaCode.trim().length === 6 && !mfaBusy) {
                        void handleMfaVerify();
                      }
                    }}
                    className="w-full sm:w-48 px-4 py-2.5 rounded-xl bg-white border border-[#E4DDCA] font-mono text-center text-lg tracking-widest font-black text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
                    autoFocus
                  />
                  <div className="flex items-center space-x-2 w-full sm:w-auto">
                    <button
                      type="button"
                      onClick={() => void handleMfaVerify()}
                      disabled={mfaBusy || mfaCode.trim().length !== 6}
                      className="flex-1 sm:flex-initial px-5 py-2.5 rounded-xl bg-[#6C5119] hover:bg-[#594214] text-white text-xs font-bold transition-colors disabled:opacity-50 cursor-pointer shadow-2xs"
                    >
                      {mfaBusy ? "Verifying…" : "✓ Verify & Activate 2FA"}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setMfaSecret(null);
                        setMfaRecoveryCodes([]);
                        setMfaCode("");
                        setMfaPassword("");
                      }}
                      className="px-3.5 py-2.5 rounded-xl bg-[#EDE8D8] text-[#24251C] text-xs font-semibold hover:bg-[#E4DDCA] transition-colors cursor-pointer"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Case 3: MFA Not Enabled & Setup Not Started */}
          {!mfaStatus?.mfa_enabled && !mfaSecret && (
            <div className="space-y-4">
              <div className="p-4 rounded-xl bg-[#F2EDE0]/60 border border-[#E4DDCA] space-y-2">
                <div className="flex items-center space-x-2 text-[#24251C] font-bold text-sm">
                  <span>🔐</span>
                  <span>Enhance your faculty account security</span>
                </div>
                <p className="text-xs text-[#77735F] leading-relaxed">
                  Two-factor authentication adds an essential second verification step. When logging in, you will provide both your password and a dynamic verification code generated by Google Authenticator, Microsoft Authenticator, or Authy.
                </p>
              </div>

              {!isEnrollmentOpen ? (
                <button
                  type="button"
                  onClick={() => setIsEnrollmentOpen(true)}
                  className="px-4 py-2.5 rounded-xl bg-[#3F451F] text-[#EDE8D8] text-xs font-bold hover:bg-[#343919] transition-colors cursor-pointer shadow-2xs flex items-center space-x-2"
                >
                  <span>🚀</span>
                  <span>Set Up Two-Factor Authentication</span>
                </button>
              ) : (
                <div className="p-4 rounded-xl bg-white border border-[#E4DDCA] space-y-3">
                  <h4 className="text-xs font-bold text-[#24251C]">
                    Enter your account password to begin enrollment
                  </h4>
                  <div className="flex flex-col sm:flex-row gap-3">
                    <input
                      type="password"
                      placeholder="Account password"
                      value={mfaPassword}
                      onChange={(e) => setMfaPassword(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && mfaPassword && !mfaBusy) {
                          void handleMfaEnable();
                        }
                      }}
                      className={inputClass}
                      autoFocus
                    />
                    <div className="flex items-center space-x-2 shrink-0">
                      <button
                        type="button"
                        onClick={() => void handleMfaEnable()}
                        disabled={mfaBusy || !mfaPassword}
                        className="px-4 py-2.5 rounded-xl bg-[#3F451F] text-[#EDE8D8] text-xs font-bold hover:bg-[#343919] transition-colors disabled:opacity-50 cursor-pointer"
                      >
                        {mfaBusy ? "Preparing…" : "Continue →"}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setIsEnrollmentOpen(false);
                          setMfaPassword("");
                        }}
                        className="px-3.5 py-2.5 rounded-xl bg-[#EDE8D8] text-[#24251C] text-xs font-semibold hover:bg-[#E4DDCA] transition-colors cursor-pointer"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
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
              onClick={() => void handleOpenRevokeModal()}
              disabled={isLoadingSessions}
              className="px-3.5 py-2 rounded-xl border border-rose-300 text-rose-700 text-xs font-bold hover:bg-rose-50 transition-colors disabled:opacity-50 cursor-pointer flex items-center gap-1.5"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
              </svg>
              <span>Sign out all other devices</span>
            </button>
            {revokeSuccessMessage && (
              <p className="text-xs font-semibold text-emerald-700 bg-emerald-50 px-2.5 py-1 rounded-lg border border-emerald-200">
                ✓ {revokeSuccessMessage}
              </p>
            )}
            {sessionsError && <p className="text-xs font-semibold text-rose-700">{sessionsError}</p>}
          </div>

          {/* Security Verification Modal for Revoking All Other Devices */}
          {isRevokeModalOpen && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4 animate-fadeIn">
              <div className="bg-[#FAF8F5] border border-[#E4DDCA] rounded-2xl max-w-md w-full p-6 shadow-xl space-y-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-rose-100 border border-rose-200 flex items-center justify-center text-rose-700 shrink-0">
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                    </svg>
                  </div>
                  <div>
                    <h3 className="text-base font-bold text-[#24251C]">Security Verification</h3>
                    <p className="text-xs text-[#77735F]">Sign out all other active devices</p>
                  </div>
                </div>

                <div className="text-xs text-[#24251C] space-y-2 bg-[#F2EDE0] p-3.5 rounded-xl border border-[#E4DDCA]">
                  <p className="font-medium">
                    To prevent unauthorized lockouts, a 6-digit confirmation code was sent to:
                  </p>
                  <div className="font-mono font-bold text-[#6C5119] text-xs">
                    {revokeOtpData?.email || "your registered email"}
                  </div>
                  <p className="text-[11px] text-[#77735F]">
                    Enter this code below to terminate sessions on all other phones, computers, and browsers.
                  </p>
                  {revokeOtpData?.dev_otp && (
                    <div className="mt-2 text-[11px] font-mono bg-amber-50 text-amber-800 p-2 rounded-lg border border-amber-200">
                      Dev hint: Verification Code is <strong>{revokeOtpData.dev_otp}</strong>
                    </div>
                  )}
                </div>

                {revokeModalError && (
                  <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-700 font-medium">
                    {revokeModalError}
                  </div>
                )}

                <div>
                  <label className="block text-xs font-bold text-[#24251C] mb-1">
                    6-Digit Security Code
                  </label>
                  <input
                    type="text"
                    maxLength={6}
                    placeholder="000000"
                    value={revokeOtpCode}
                    onChange={(e) => setRevokeOtpCode(e.target.value.replace(/\D/g, ""))}
                    className="w-full text-center text-2xl font-mono tracking-widest py-3 px-4 rounded-xl border border-[#E4DDCA] bg-white text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-500"
                    autoFocus
                  />
                </div>

                <div className="flex items-center justify-between gap-3 pt-2">
                  <button
                    type="button"
                    onClick={() => void handleResendOtp()}
                    disabled={isRequestingOtp}
                    className="text-xs font-semibold text-[#6C5119] hover:underline disabled:opacity-50 cursor-pointer"
                  >
                    {isRequestingOtp ? "Sending code…" : "Resend email code"}
                  </button>

                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        setIsRevokeModalOpen(false);
                        setRevokeOtpCode("");
                        setRevokeModalError(null);
                      }}
                      disabled={isSubmittingRevoke}
                      className="px-4 py-2 rounded-xl border border-[#E4DDCA] text-xs font-bold text-[#77735F] hover:bg-[#F2EDE0] transition-colors cursor-pointer"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleConfirmRevokeAll()}
                      disabled={isSubmittingRevoke || revokeOtpCode.length < 6}
                      className="px-4 py-2 rounded-xl bg-rose-600 text-white text-xs font-bold hover:bg-rose-700 transition-colors disabled:opacity-50 cursor-pointer flex items-center gap-1.5"
                    >
                      {isSubmittingRevoke ? "Revoking…" : "Confirm & Sign Out All"}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}


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
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {(
            [
              { value: "warm", label: "Warm (RollCall)", hint: "Default cream and olive" },
              { value: "light", label: "Light", hint: "Neutral light surfaces" },
              { value: "dark", label: "Dark", hint: "Reduced glare at night" },
            ] as const
          ).map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => updatePreference("theme", option.value as ThemePreference)}
              className={`p-4 rounded-xl border text-left transition-all cursor-pointer ${
                preferences.theme === option.value
                  ? "border-[#6C5119] bg-[#EDE8D8]/50 ring-1 ring-[#6C5119]"
                  : "border-[#E4DDCA] bg-white hover:border-[#A77A13]"
              }`}
            >
              <span className="block text-sm font-bold text-[#24251C]">{option.label}</span>
              <span className="block text-[11px] text-[#77735F] mt-0.5">{option.hint}</span>
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
