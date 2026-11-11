import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";

export function LoginView() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [userId, setUserId] = useState("");
  const [password, setPassword] = useState("");
  const [adminKey, setAdminKey] = useState("");
  const [showAdminKey, setShowAdminKey] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!userId.trim()) {
      setErrorMessage("Please enter your User ID.");
      return;
    }
    setIsSubmitting(true);
    setErrorMessage(null);

    try {
      await login({
        userId: userId.trim(),
        password,
        adminKey: showAdminKey && adminKey.trim() ? adminKey.trim() : undefined,
      });
      navigate("/");
    } catch (err: unknown) {
      if (err instanceof Error) {
        setErrorMessage(`Authentication failed: ${err.message}. Please verify your credentials.`);
      } else {
        setErrorMessage("Authentication failed. Invalid credentials or backend service is unreachable.");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-[#F2EDE0]">
      <div className="w-full max-w-md bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl shadow-lg p-6 sm:p-8 space-y-6">
        {/* Brand Header */}
        <div className="text-center space-y-2">
          <div className="w-12 h-12 rounded-xl bg-[#3F451F] text-[#EDE8D8] flex items-center justify-center mx-auto shadow-sm">
            <svg className="w-7 h-7" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 3L1 9l4 2.18v6L12 21l7-3.82v-6l2-1.09V17h2V9L12 3zm6.82 6L12 12.72 5.18 9 12 5.28 18.82 9zM17 15.99l-5 2.73-5-2.73v-3.72L12 15l5-2.73v3.72z" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-[#24251C]">
            RollCall AI
          </h1>
          <p className="text-xs font-medium text-[#77735F]">
            Attendance, Simplified
          </p>
        </div>

        {/* Error Alert */}
        {errorMessage && (
          <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 text-xs flex items-start space-x-2">
            <svg className="w-4 h-4 text-rose-500 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span>{errorMessage}</span>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="user_id" className="block text-xs font-semibold text-[#24251C] mb-1.5">
              User ID
            </label>
            <input
              id="user_id"
              type="text"
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
              placeholder="Enter your User ID"
              required
              className="w-full px-3.5 py-2.5 rounded-xl bg-white border border-[#E4DDCA] text-sm text-[#24251C] placeholder-[#77735F]/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119] transition-all"
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-xs font-semibold text-[#24251C] mb-1.5">
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••••••"
              required
              className="w-full px-3.5 py-2.5 rounded-xl bg-white border border-[#E4DDCA] text-sm text-[#24251C] placeholder-[#77735F]/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119] transition-all"
            />
          </div>

          {/* Admin Elevation Key Option */}
          <div className="pt-1">
            <div className="flex items-center justify-between">
              <button
                type="button"
                onClick={() => setShowAdminKey(!showAdminKey)}
                className="text-xs text-[#6C5119] hover:underline font-medium cursor-pointer"
              >
                {showAdminKey ? "− Hide Admin Elevation Key" : "+ Have an Admin Key?"}
              </button>
            </div>

            {showAdminKey && (
              <div className="mt-2">
                <input
                  type="password"
                  value={adminKey}
                  onChange={(e) => setAdminKey(e.target.value)}
                  placeholder="Enter admin promotion secret..."
                  className="w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs text-[#24251C] placeholder-[#77735F]/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
                />
              </div>
            )}
          </div>

          {/* Submit Button */}
          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full py-2.5 px-4 rounded-xl bg-[#3F451F] hover:bg-[#343919] text-[#EDE8D8] text-sm font-bold shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119] disabled:opacity-50 cursor-pointer"
          >
            {isSubmitting ? "Authenticating..." : "Sign In"}
          </button>
        </form>
      </div>
    </div>
  );
}