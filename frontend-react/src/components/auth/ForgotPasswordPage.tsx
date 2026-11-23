import React, { useState, useEffect, useRef } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { apiClient } from "@/services/api/client";

type ResetStep = "request" | "otp" | "password" | "success";

interface ForgotPasswordPageProps {
  initialStep?: ResetStep;
}

export const ForgotPasswordPage: React.FC<ForgotPasswordPageProps> = ({
  initialStep = "request",
}) => {
  const navigate = useNavigate();
  const location = useLocation();

  // Retrieve state passed from navigation if any
  const navState = (location.state as { identifier?: string; resetToken?: string; otp?: string } | null) || {};

  const [step, setStep] = useState<ResetStep>(() => {
    if (navState.resetToken) return "password";
    if (navState.identifier && initialStep === "otp") return "otp";
    return initialStep;
  });

  const [identifier, setIdentifier] = useState(navState.identifier || "");
  const [maskedEmail, setMaskedEmail] = useState<string | null>(null);
  const [lookupResult, setLookupResult] = useState<{ found: boolean; user_id?: string; email_masked?: string } | null>(null);
  const [isLookingUp, setIsLookingUp] = useState(false);
  const [otpCode, setOtpCode] = useState(navState.otp || "");
  const [resetToken, setResetToken] = useState(navState.resetToken || "");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  // Status and feedback
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [infoMessage, setInfoMessage] = useState<string | null>(null);
  const [devOtp, setDevOtp] = useState<string | null>(navState.otp || null);

  // Resend OTP countdown (60 seconds)
  const [resendSeconds, setResendSeconds] = useState(0);
  const timerRef = useRef<NodeJS.Timeout | null>(null);

  // Auto-redirect countdown on success
  const [redirectCountdown, setRedirectCountdown] = useState(4);

  // Live account lookup helper
  const handleLookupAccount = React.useCallback(async (targetId?: string) => {
    const cleanId = (targetId ?? identifier).trim();
    if (!cleanId) {
      setLookupResult(null);
      return;
    }
    setIsLookingUp(true);
    try {
      const res = await apiClient.post<{
        found: boolean;
        user_id?: string;
        email_masked?: string;
        message?: string;
      }>("/api/v1/auth/password/lookup-account", {
        user_identifier: cleanId,
      });
      setLookupResult(res);
      if (res.found && res.email_masked) {
        setMaskedEmail(res.email_masked);
      }
    } catch {
      setLookupResult(null);
    } finally {
      setIsLookingUp(false);
    }
  }, [identifier]);

  // Auto-lookup on mount if an identifier was passed
  useEffect(() => {
    if (navState.identifier && step === "request") {
      void handleLookupAccount(navState.identifier);
    }
  }, [navState.identifier, step, handleLookupAccount]);

  useEffect(() => {
    if (resendSeconds > 0) {
      timerRef.current = setTimeout(() => {
        setResendSeconds((prev) => prev - 1);
      }, 1000);
    }
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [resendSeconds]);

  // Handle redirect after success
  useEffect(() => {
    if (step === "success") {
      const interval = setInterval(() => {
        setRedirectCountdown((prev) => {
          if (prev <= 1) {
            clearInterval(interval);
            navigate("/login");
            return 0;
          }
          return prev - 1;
        });
      }, 1000);
      return () => clearInterval(interval);
    }
  }, [step, navigate]);

  // Password validation checks
  const hasMinLength = newPassword.length >= 8;
  const hasUppercase = /[A-Z]/.test(newPassword);
  const hasLowercase = /[a-z]/.test(newPassword);
  const hasNumber = /[0-9]/.test(newPassword);
  const hasSpecialChar = /[!@#$%^&*()[\]{}<>?|:;,.~+\-=/\\]/.test(newPassword);
  const passwordsMatch = newPassword.length > 0 && newPassword === confirmPassword;
  const isPasswordValid =
    hasMinLength && hasUppercase && hasLowercase && hasNumber && hasSpecialChar && passwordsMatch;

  // Step 1: Request OTP from backend
  const handleRequestOtp = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const cleanId = identifier.trim();
    if (!cleanId) {
      setErrorMessage("Please enter your registered User ID or email address.");
      return;
    }

    setIsLoading(true);
    setErrorMessage(null);
    setInfoMessage(null);

    try {
      const res = await apiClient.post<{
        message: string;
        otp_expires_in_seconds?: number;
        otp?: string;
        email_masked?: string;
      }>("/api/v1/auth/password/forgot", {
        user_identifier: cleanId,
      });

      if (res.email_masked) {
        setMaskedEmail(res.email_masked);
      }

      setInfoMessage(
        res.message || `A 6-digit OTP has been sent to the email address registered with ${cleanId}.`
      );
      if (res.otp) {
        setDevOtp(res.otp);
      }
      setResendSeconds(60);
      setStep("otp");
    } catch (err: unknown) {
      const errMessage = (err as Error)?.message || "Failed to send reset code. Please verify your identifier and try again.";
      setErrorMessage(errMessage);
    } finally {
      setIsLoading(false);
    }
  };

  // Step 2: Verify OTP
  const handleVerifyOtp = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const cleanOtp = otpCode.trim().replace(/\D/g, "");
    if (cleanOtp.length !== 6) {
      setErrorMessage("Please enter the complete 6-digit verification code.");
      return;
    }

    setIsLoading(true);
    setErrorMessage(null);

    try {
      const res = await apiClient.post<{
        message: string;
        reset_token?: string;
      }>("/api/v1/auth/password/verify-otp", {
        user_identifier: identifier.trim(),
        otp_code: cleanOtp,
      });

      if (res.reset_token) {
        setResetToken(res.reset_token);
      }
      setInfoMessage("Verification code accepted! Please set your new password.");
      setStep("password");
    } catch (err: unknown) {
      const errMessage = (err as Error)?.message || "Invalid or expired verification code. Please check and try again.";
      setErrorMessage(errMessage);
    } finally {
      setIsLoading(false);
    }
  };

  // Step 3: Complete Password Reset
  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isPasswordValid) {
      setErrorMessage("Please ensure your password satisfies all security requirements and matches.");
      return;
    }

    setIsLoading(true);
    setErrorMessage(null);

    try {
      if (resetToken) {
        // Preferred route with validated reset token
        await apiClient.post("/api/v1/auth/password/reset/confirm", {
          reset_token: resetToken,
          new_password: newPassword,
        });
      } else {
        // Direct atomic verify + reset
        await apiClient.post("/api/v1/auth/password/verify-otp", {
          user_identifier: identifier.trim(),
          otp_code: otpCode.trim(),
          new_password: newPassword,
        });
      }

      setStep("success");
    } catch (err: unknown) {
      const errMessage = (err as Error)?.message || "Failed to update password. Please try again.";
      setErrorMessage(errMessage);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-[#F2EDE0]">
      <div className="w-full max-w-md bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl shadow-lg p-6 sm:p-8 space-y-6">
        {/* Brand Header */}
        <div className="text-center space-y-2">
          <Link to="/login" className="inline-block transition-transform hover:scale-105">
            <div className="w-12 h-12 rounded-xl bg-[#3F451F] text-[#EDE8D8] flex items-center justify-center mx-auto shadow-sm">
              <svg className="w-7 h-7" fill="currentColor" viewBox="0 0 24 24">
                <path d="M12 3L1 9l4 2.18v6L12 21l7-3.82v-6l2-1.09V17h2V9L12 3zm6.82 6L12 12.72 5.18 9 12 5.28 18.82 9zM17 15.99l-5 2.73-5-2.73v-3.72L12 15l5-2.73v3.72z" />
              </svg>
            </div>
          </Link>
          <h1 className="text-2xl font-bold tracking-tight text-[#24251C]">
            {step === "success"
              ? "Password Reset Complete"
              : step === "password"
              ? "Set New Password"
              : step === "otp"
              ? "Enter Verification Code"
              : "Reset Your Password"}
          </h1>
          <p className="text-xs font-medium text-[#77735F]">
            {step === "success"
              ? "Your account security has been updated."
              : step === "password"
              ? "Choose a strong, unique password for RollCall AI."
              : step === "otp"
              ? `We sent a 6-digit code to ${maskedEmail || identifier}.`
              : "Enter your User ID or email to receive a password reset code."}
          </p>
        </div>

        {/* Step Indicator Progress Bar */}
        {step !== "success" && (
          <div className="flex items-center justify-between gap-2 px-2">
            <div
              className={`flex-1 h-1.5 rounded-full transition-all duration-300 ${
                step === "request" || step === "otp" || step === "password"
                  ? "bg-[#3F451F]"
                  : "bg-[#E4DDCA]"
              }`}
            />
            <div
              className={`flex-1 h-1.5 rounded-full transition-all duration-300 ${
                step === "otp" || step === "password"
                  ? "bg-[#3F451F]"
                  : "bg-[#E4DDCA]"
              }`}
            />
            <div
              className={`flex-1 h-1.5 rounded-full transition-all duration-300 ${
                step === "password" ? "bg-[#3F451F]" : "bg-[#E4DDCA]"
              }`}
            />
          </div>
        )}

        {/* Error Alert */}
        {errorMessage && (
          <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 text-xs flex items-start space-x-2 animate-fadeIn">
            <svg
              className="w-4 h-4 text-rose-500 shrink-0 mt-0.5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
            <span className="flex-1">{errorMessage}</span>
            <button
              type="button"
              onClick={() => setErrorMessage(null)}
              className="text-rose-500 hover:text-rose-700 ml-1 font-bold"
            >
              ×
            </button>
          </div>
        )}

        {/* Info Message */}
        {infoMessage && !errorMessage && (
          <div className="p-3 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs flex items-start space-x-2">
            <svg
              className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M5 13l4 4L19 7"
              />
            </svg>
            <span>{infoMessage}</span>
          </div>
        )}

        {/* Development Environment OTP Helper Badge */}
        {devOtp && (step === "otp" || step === "password") && (
          <div className="p-2.5 rounded-xl bg-amber-50 border border-amber-300 text-amber-900 text-xs flex items-center justify-between shadow-2xs">
            <span className="flex items-center gap-1.5 font-medium">
              <span>⚡</span>
              <span>Dev Mailbox Code: <strong>{devOtp}</strong></span>
            </span>
            {step === "otp" && (
              <button
                type="button"
                onClick={() => setOtpCode(devOtp)}
                className="px-2 py-0.5 rounded-md bg-amber-200 hover:bg-amber-300 text-amber-950 font-bold text-[11px] transition-colors cursor-pointer"
              >
                Auto-fill
              </button>
            )}
          </div>
        )}

        {/* ========================================================================= */}
        {/* STEP 1: REQUEST OTP                                                       */}
        {/* ========================================================================= */}
        {step === "request" && (
          <form onSubmit={handleRequestOtp} className="space-y-4">
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label htmlFor="identifier" className="block text-xs font-semibold text-[#24251C]">
                  Teacher Username or Email
                </label>
                {identifier.trim() && (
                  <button
                    type="button"
                    onClick={() => void handleLookupAccount()}
                    disabled={isLookingUp || isLoading}
                    className="text-[11px] font-semibold text-[#6C5119] hover:underline cursor-pointer"
                  >
                    {isLookingUp ? "Fetching email..." : "Check Registered Email"}
                  </button>
                )}
              </div>
              <input
                id="identifier"
                type="text"
                value={identifier}
                onChange={(e) => {
                  setIdentifier(e.target.value);
                  setLookupResult(null);
                }}
                onBlur={() => {
                  if (identifier.trim() && !lookupResult) {
                    void handleLookupAccount();
                  }
                }}
                placeholder="e.g. test_faculty, faculty_ai, or your username"
                required
                autoFocus
                disabled={isLoading}
                className="w-full px-3.5 py-2.5 rounded-xl bg-white border border-[#E4DDCA] text-sm text-[#24251C] placeholder-[#77735F]/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119] transition-all"
              />
              <p className="text-[11px] text-[#77735F] mt-1">
                Enter your username. The system automatically looks up your account and sends the OTP to your registered email.
              </p>
            </div>

            {/* Found Account Preview Card */}
            {lookupResult?.found && (
              <div className="p-3 rounded-xl bg-emerald-50 border border-emerald-200 text-xs text-emerald-900 space-y-1 animate-fadeIn">
                <div className="flex items-center justify-between font-bold">
                  <span className="flex items-center gap-1.5">
                    <span>✓</span> Account Found: <span className="font-mono">{lookupResult.user_id}</span>
                  </span>
                  <span className="text-[10px] uppercase font-bold px-2 py-0.5 rounded-full bg-emerald-200 text-emerald-900">
                    Verified
                  </span>
                </div>
                <p className="text-[11px] text-emerald-800">
                  Registered Destination Email: <strong className="font-mono text-emerald-950">{lookupResult.email_masked}</strong>
                </p>
              </div>
            )}

            {lookupResult && !lookupResult.found && (
              <div className="p-2.5 rounded-xl bg-amber-50 border border-amber-200 text-xs text-amber-900">
                No active account found for username &ldquo;{identifier}&rdquo;. Please verify your username.
              </div>
            )}

            <button
              type="submit"
              disabled={isLoading || !identifier.trim()}
              className="w-full py-2.5 px-4 rounded-xl bg-[#3F451F] hover:bg-[#343919] text-[#EDE8D8] text-sm font-bold shadow-md hover:shadow-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center space-x-2 cursor-pointer"
            >
              {isLoading ? (
                <>
                  <span className="w-4 h-4 border-2 border-[#EDE8D8] border-t-transparent rounded-full animate-spin" />
                  <span>Looking up registered email & sending OTP...</span>
                </>
              ) : (
                <>
                  <span>
                    {lookupResult?.found
                      ? `Send OTP to ${lookupResult.email_masked}`
                      : "Send Verification Code"}
                  </span>
                  <span>➔</span>
                </>
              )}
            </button>

            <div className="pt-2 text-center">
              <Link
                to="/login"
                className="text-xs font-semibold text-[#6C5119] hover:underline flex items-center justify-center gap-1"
              >
                <span>←</span>
                <span>Back to Login</span>
              </Link>
            </div>
          </form>
        )}

        {/* ========================================================================= */}
        {/* STEP 2: VERIFY OTP                                                        */}
        {/* ========================================================================= */}
        {step === "otp" && (
          <form onSubmit={handleVerifyOtp} className="space-y-4">
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label htmlFor="otp_code" className="block text-xs font-semibold text-[#24251C]">
                  6-Digit Verification Code
                </label>
                <button
                  type="button"
                  onClick={() => {
                    setErrorMessage(null);
                    setStep("request");
                  }}
                  className="text-[11px] font-semibold text-[#6C5119] hover:underline"
                >
                  Change Email / ID
                </button>
              </div>

              <input
                id="otp_code"
                type="text"
                inputMode="numeric"
                maxLength={6}
                value={otpCode}
                onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                placeholder="• • • • • •"
                autoFocus
                required
                disabled={isLoading}
                className="w-full text-center tracking-[0.5em] text-xl font-bold py-3 rounded-xl bg-white border border-[#E4DDCA] text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119] transition-all"
              />
              <p className="text-[11px] text-[#77735F] mt-1 text-center">
                Enter the 6-digit one-time code sent to your registered email.
              </p>
            </div>

            {/* Recipient Confirmation Box */}
            <div className="p-3 rounded-xl bg-white border border-[#E4DDCA] text-xs text-[#24251C] space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-[#77735F]">Sent To:</span>
                <span className="font-mono font-bold text-[#3F451F]">{maskedEmail || identifier}</span>
              </div>
              <div className="flex items-center justify-between text-[10px] text-[#77735F]">
                <span>Status:</span>
                <span className="text-emerald-700 font-semibold">✓ Dispatched to Mailbox</span>
              </div>
            </div>

            <button
              type="submit"
              disabled={isLoading || otpCode.trim().length !== 6}
              className="w-full py-2.5 px-4 rounded-xl bg-[#3F451F] hover:bg-[#343919] text-[#EDE8D8] text-sm font-bold shadow-md hover:shadow-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center space-x-2 cursor-pointer"
            >
              {isLoading ? (
                <>
                  <span className="w-4 h-4 border-2 border-[#EDE8D8] border-t-transparent rounded-full animate-spin" />
                  <span>Verifying Code...</span>
                </>
              ) : (
                <>
                  <span>Verify Code</span>
                  <span>➔</span>
                </>
              )}
            </button>

            {/* Resend OTP Button */}
            <div className="pt-2 flex items-center justify-between text-xs">
              <Link
                to="/login"
                className="font-semibold text-[#6C5119] hover:underline flex items-center gap-1"
              >
                <span>←</span>
                <span>Cancel</span>
              </Link>

              <button
                type="button"
                onClick={() => void handleRequestOtp()}
                disabled={isLoading || resendSeconds > 0}
                className="font-semibold text-[#6C5119] hover:underline disabled:text-[#77735F] disabled:cursor-not-allowed cursor-pointer"
              >
                {resendSeconds > 0 ? `Resend code in ${resendSeconds}s` : "Resend OTP Code"}
              </button>
            </div>
          </form>
        )}

        {/* ========================================================================= */}
        {/* STEP 3: SET NEW PASSWORD                                                  */}
        {/* ========================================================================= */}
        {step === "password" && (
          <form onSubmit={handleResetPassword} className="space-y-4">
            <div>
              <label htmlFor="new_password" className="block text-xs font-semibold text-[#24251C] mb-1.5">
                New Password
              </label>
              <div className="relative">
                <input
                  id="new_password"
                  type={showPassword ? "text" : "password"}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="Create a strong password"
                  required
                  autoFocus
                  disabled={isLoading}
                  className="w-full pl-3.5 pr-10 py-2.5 rounded-xl bg-white border border-[#E4DDCA] text-sm text-[#24251C] placeholder-[#77735F]/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119] transition-all"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[#77735F] hover:text-[#24251C] cursor-pointer p-1"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? "👁️" : "🙈"}
                </button>
              </div>
            </div>

            <div>
              <label htmlFor="confirm_password" className="block text-xs font-semibold text-[#24251C] mb-1.5">
                Confirm New Password
              </label>
              <div className="relative">
                <input
                  id="confirm_password"
                  type={showConfirmPassword ? "text" : "password"}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="Repeat your new password"
                  required
                  disabled={isLoading}
                  className="w-full pl-3.5 pr-10 py-2.5 rounded-xl bg-white border border-[#E4DDCA] text-sm text-[#24251C] placeholder-[#77735F]/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119] transition-all"
                />
                <button
                  type="button"
                  onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[#77735F] hover:text-[#24251C] cursor-pointer p-1"
                  aria-label={showConfirmPassword ? "Hide password" : "Show password"}
                >
                  {showConfirmPassword ? "👁️" : "🙈"}
                </button>
              </div>
            </div>

            {/* Password Security Policy Checklist */}
            <div className="p-3 rounded-xl bg-white border border-[#E4DDCA] space-y-1.5 text-xs">
              <span className="font-bold text-[#24251C] block text-[11px] mb-1 uppercase tracking-wider">
                Password Requirements:
              </span>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-1 text-[11px]">
                <div className={`flex items-center gap-1.5 ${hasMinLength ? "text-emerald-700 font-semibold" : "text-[#77735F]"}`}>
                  <span>{hasMinLength ? "✓" : "○"}</span>
                  <span>8+ characters</span>
                </div>
                <div className={`flex items-center gap-1.5 ${hasUppercase ? "text-emerald-700 font-semibold" : "text-[#77735F]"}`}>
                  <span>{hasUppercase ? "✓" : "○"}</span>
                  <span>1 uppercase letter</span>
                </div>
                <div className={`flex items-center gap-1.5 ${hasLowercase ? "text-emerald-700 font-semibold" : "text-[#77735F]"}`}>
                  <span>{hasLowercase ? "✓" : "○"}</span>
                  <span>1 lowercase letter</span>
                </div>
                <div className={`flex items-center gap-1.5 ${hasNumber ? "text-emerald-700 font-semibold" : "text-[#77735F]"}`}>
                  <span>{hasNumber ? "✓" : "○"}</span>
                  <span>1 number (0-9)</span>
                </div>
                <div className={`flex items-center gap-1.5 ${hasSpecialChar ? "text-emerald-700 font-semibold" : "text-[#77735F]"}`}>
                  <span>{hasSpecialChar ? "✓" : "○"}</span>
                  <span>1 special symbol</span>
                </div>
                <div className={`flex items-center gap-1.5 ${passwordsMatch ? "text-emerald-700 font-semibold" : "text-[#77735F]"}`}>
                  <span>{passwordsMatch ? "✓" : "○"}</span>
                  <span>Passwords match</span>
                </div>
              </div>
            </div>

            <button
              type="submit"
              disabled={isLoading || !isPasswordValid}
              className="w-full py-2.5 px-4 rounded-xl bg-[#3F451F] hover:bg-[#343919] text-[#EDE8D8] text-sm font-bold shadow-md hover:shadow-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center space-x-2 cursor-pointer"
            >
              {isLoading ? (
                <>
                  <span className="w-4 h-4 border-2 border-[#EDE8D8] border-t-transparent rounded-full animate-spin" />
                  <span>Updating Password...</span>
                </>
              ) : (
                <>
                  <span>Reset Password</span>
                  <span>➔</span>
                </>
              )}
            </button>
          </form>
        )}

        {/* ========================================================================= */}
        {/* STEP 4: SUCCESS CONFIRMATION                                              */}
        {/* ========================================================================= */}
        {step === "success" && (
          <div className="text-center space-y-5 py-4 animate-fadeIn">
            <div className="w-16 h-16 rounded-full bg-emerald-100 text-emerald-600 flex items-center justify-center mx-auto shadow-inner">
              <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
              </svg>
            </div>

            <div className="space-y-1">
              <h3 className="text-lg font-bold text-[#24251C]">
                Password Reset Successfully!
              </h3>
              <p className="text-xs text-[#77735F] max-w-xs mx-auto">
                All existing sessions have been signed out for security. You can now log in with your new password.
              </p>
            </div>

            <div className="pt-2">
              <button
                type="button"
                onClick={() => navigate("/login")}
                className="w-full py-2.5 px-4 rounded-xl bg-[#3F451F] hover:bg-[#343919] text-[#EDE8D8] text-sm font-bold shadow-md hover:shadow-lg transition-all flex items-center justify-center gap-2 cursor-pointer"
              >
                <span>Proceed to Login</span>
                <span>({redirectCountdown}s) ➔</span>
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default ForgotPasswordPage;
