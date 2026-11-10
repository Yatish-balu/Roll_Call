"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useAuth } from "@/hooks/useAuth";
import { checkBackendHealth } from "@/services/api/health";

export function SettingsView() {
  const { session, logout } = useAuth();
  const [healthStatus, setHealthStatus] = useState<{
    ok: boolean;
    timestamp: string;
    version?: string;
  } | null>(null);
  const [isCheckingHealth, setIsCheckingHealth] = useState(false);

  // Preference Toggles (Local Storage)
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [soundFeedback, setSoundFeedback] = useState(false);
  const [emailDigest, setEmailDigest] = useState(true);

  const checkHealth = useCallback(async () => {
    setIsCheckingHealth(true);
    try {
      const res = await checkBackendHealth();
      setHealthStatus({
        ok: res.status === "healthy" || res.status === "ok",
        timestamp: new Date().toLocaleTimeString(),
        version: "v2.6.0-fastapi",
      });
    } catch {
      setHealthStatus({
        ok: false,
        timestamp: new Date().toLocaleTimeString(),
      });
    } finally {
      setIsCheckingHealth(false);
    }
  }, []);

  useEffect(() => {
    let isMounted = true;
    Promise.resolve().then(() => {
      if (isMounted) void checkHealth();
    });
    return () => {
      isMounted = false;
    };
  }, [checkHealth]);

  return (
    <div className="space-y-6 max-w-4xl">
      {/* Header Bar */}
      <div>
        <h1 className="text-2xl font-bold text-[#24251C] tracking-tight">System & Account Settings</h1>
        <p className="text-sm text-[#77735F] mt-0.5">
          User profile attributes, attendance preferences, and backend server diagnostics.
        </p>
      </div>

      {/* User Profile Card */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-5 shadow-sm">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-4">
            <div className="w-14 h-14 rounded-2xl bg-[#3F451F] text-[#FBF8F0] flex items-center justify-center font-bold text-xl uppercase shadow-xs">
              {session.userId?.[0] || "U"}
            </div>
            <div>
              <h2 className="text-lg font-bold text-[#24251C]">{session.name || session.userId || "Active User"}</h2>
              <div className="flex items-center gap-2 mt-1">
                <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-bold bg-[#6C5119]/15 text-[#6C5119] border border-[#6C5119]/30">
                  {session.role || "FACULTY"}
                </span>
                <span className="text-xs text-[#77735F] font-mono">ID: {session.userId || "—"}</span>
              </div>
            </div>
          </div>

          <button
            onClick={logout}
            className="px-3.5 py-1.5 rounded-xl border border-red-300 text-xs font-semibold text-red-700 hover:bg-red-50 transition-colors"
          >
            Sign Out
          </button>
        </div>

        <div className="mt-5 pt-4 border-t border-[#E4DDCA] grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs text-[#77735F]">
          <div>
            <span className="font-semibold text-[#24251C]">Assigned Subject Codes:</span>
            <div className="flex flex-wrap gap-1.5 mt-1.5">
              {session.subjectCodes && session.subjectCodes.length > 0 ? (
                session.subjectCodes.map((sub: string) => (
                  <span
                    key={sub}
                    className="px-2 py-0.5 rounded-md font-mono font-semibold bg-[#F2EDE0] border border-[#E4DDCA] text-[#3F451F]"
                  >
                    {sub}
                  </span>
                ))
              ) : (
                <span className="italic text-[#77735F]">Institutional Administrator (All Subjects)</span>
              )}
            </div>
          </div>
          <div>
            <span className="font-semibold text-[#24251C]">Security Token Expiry:</span>
            <p className="mt-1 font-mono">Session Token Active (Sliding window refresh)</p>
          </div>
        </div>
      </div>

      {/* Application Preferences */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-5 shadow-sm space-y-4">
        <h2 className="text-base font-bold text-[#24251C]">Application Preferences</h2>

        <div className="space-y-3 divide-y divide-[#E4DDCA]/70 text-sm">
          <div className="flex items-center justify-between pt-2">
            <div>
              <p className="font-semibold text-[#24251C]">Real-time Roster Auto-Refresh</p>
              <p className="text-xs text-[#77735F]">
                Periodically check for active session updates and OCR scanning tasks.
              </p>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
                className="sr-only peer"
              />
              <div className="w-11 h-6 bg-[#E4DDCA] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[#3F451F]" />
            </label>
          </div>

          <div className="flex items-center justify-between pt-3">
            <div>
              <p className="font-semibold text-[#24251C]">Audio & Tone Feedback</p>
              <p className="text-xs text-[#77735F]">
                Play soft chime upon successful roster confirmation or anomaly detection.
              </p>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={soundFeedback}
                onChange={(e) => setSoundFeedback(e.target.checked)}
                className="sr-only peer"
              />
              <div className="w-11 h-6 bg-[#E4DDCA] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[#3F451F]" />
            </label>
          </div>

          <div className="flex items-center justify-between pt-3">
            <div>
              <p className="font-semibold text-[#24251C]">Department Attendance Digest</p>
              <p className="text-xs text-[#77735F]">
                Receive automated summary reports at the conclusion of each academic day.
              </p>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={emailDigest}
                onChange={(e) => setEmailDigest(e.target.checked)}
                className="sr-only peer"
              />
              <div className="w-11 h-6 bg-[#E4DDCA] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[#3F451F]" />
            </label>
          </div>
        </div>
      </div>

      {/* Backend Health Diagnostics */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-5 shadow-sm">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-base font-bold text-[#24251C]">Backend Diagnostics</h2>
            <p className="text-xs text-[#77735F]">
              Live status of FastAPI application server and database connectivity.
            </p>
          </div>
          <button
            onClick={() => void checkHealth()}
            disabled={isCheckingHealth}
            className="px-3 py-1.5 rounded-xl text-xs font-semibold bg-[#F2EDE0] text-[#3F451F] hover:bg-[#EAE4D4] transition-colors disabled:opacity-50"
          >
            {isCheckingHealth ? "Probing..." : "Test Connection"}
          </button>
        </div>

        <div className="p-4 bg-[#F2EDE0] border border-[#E4DDCA] rounded-xl text-xs space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[#77735F]">Endpoint:</span>
            <span className="font-mono text-[#24251C]">http://127.0.0.1:8000/health</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[#77735F]">Status:</span>
            <span
              className={`font-semibold inline-flex items-center gap-1.5 ${
                healthStatus?.ok ? "text-emerald-700" : "text-red-600"
              }`}
            >
              <span
                className={`w-2 h-2 rounded-full ${
                  healthStatus?.ok ? "bg-emerald-500" : "bg-red-500"
                }`}
              />
              {healthStatus?.ok ? "Operational (HTTP 200)" : "Unreachable or Degraded"}
            </span>
          </div>
          {healthStatus?.timestamp && (
            <div className="flex items-center justify-between">
              <span className="text-[#77735F]">Last Ping:</span>
              <span className="font-mono text-[#77735F]">{healthStatus.timestamp}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
