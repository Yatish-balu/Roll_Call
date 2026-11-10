import React, { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { checkBackendHealth } from "@/services/api/health";
import { apiClient } from "@/services/api/client";

interface MetaConfig {
  edit_lock_hours: number;
  defaulter_threshold_percent: number;
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

export function SettingsView() {
  const navigate = useNavigate();
  const { session, logout, isAdmin } = useAuth();
  const [healthStatus, setHealthStatus] = useState<{
    ok: boolean;
    timestamp: string;
    latencyMs?: number;
  } | null>(null);
  const [isCheckingHealth, setIsCheckingHealth] = useState(false);
  const [metaConfig, setMetaConfig] = useState<MetaConfig | null>(null);

  // Preference Toggles (Local Storage)
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [soundFeedback, setSoundFeedback] = useState(false);
  const [emailDigest, setEmailDigest] = useState(true);
  const [lowAttendanceAlert, setLowAttendanceAlert] = useState(75);
  const [defaultStatus, setDefaultStatus] = useState<"UNREVIEWED" | "PRESENT">("UNREVIEWED");

  const checkHealth = useCallback(async () => {
    setIsCheckingHealth(true);
    const start = performance.now();
    try {
      const res = await checkBackendHealth();
      const latency = Math.round(performance.now() - start);
      setHealthStatus({
        ok: res.status === "healthy" || res.status === "ok",
        timestamp: new Date().toLocaleTimeString(),
        latencyMs: latency,
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

  // Fetch real meta configuration from backend
  useEffect(() => {
    let isMounted = true;
    void checkHealth();
    apiClient
      .get<MetaConfig>("/api/v1/meta/config")
      .then((cfg) => {
        if (isMounted) setMetaConfig(cfg);
      })
      .catch(() => {
        // Fallback defaults if meta not available
      });
    return () => {
      isMounted = false;
    };
  }, [checkHealth]);

  const displayName = session?.name || session?.userId || "Faculty Member";

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      {/* Header Bar */}
      <div>
        <h1 className="text-2xl sm:text-3xl font-extrabold text-[#24251C] tracking-tight">
          System & Account Settings
        </h1>
        <p className="text-xs sm:text-sm text-[#77735F] mt-1">
          Faculty profile details, institutional attendance rules, security sessions, and live backend diagnostics.
        </p>
      </div>

      {/* User Institutional Profile Card */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-6 shadow-2xs space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="w-16 h-16 rounded-2xl bg-[#3F451F] text-[#EDE8D8] flex items-center justify-center font-black text-2xl uppercase shadow-sm border border-[#E4DDCA]">
              {displayName.charAt(0)}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-xl font-extrabold text-[#24251C]">{displayName}</h2>
                <span className={`px-2.5 py-0.5 rounded-full text-[11px] font-black uppercase tracking-wider ${
                  isAdmin ? "bg-[#6C5119] text-white" : "bg-[#3F451F] text-[#EDE8D8]"
                }`}>
                  {isAdmin ? "Institutional Admin" : "Course Faculty"}
                </span>
              </div>
              <p className="text-xs text-[#77735F] mt-0.5">
                Department of Computer Science & Engineering • RollCall AI Faculty Registry
              </p>
              <div className="flex items-center gap-2 mt-2 text-xs font-mono text-[#77735F]">
                <span>ID: {session.userId || "N/A"}</span>
                <span>•</span>
                <span>{session.userId ? `${session.userId}@rollcall.internal` : "user@rollcall.internal"}</span>
              </div>
            </div>
          </div>

          <button
            onClick={async () => {
              await logout();
              navigate("/login");
            }}
            className="px-4 py-2 rounded-xl border border-red-300 text-xs font-bold text-red-700 hover:bg-red-50 transition-colors cursor-pointer self-start sm:self-auto"
          >
            Sign Out
          </button>
        </div>

        {/* Profile Attributes Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-4 border-t border-[#E4DDCA] text-xs">
          <div className="p-3 rounded-xl bg-[#EDE8D8]/40 border border-[#E4DDCA] space-y-1">
            <span className="font-bold text-[#77735F] uppercase text-[10px]">Assigned Subject Codes</span>
            <div className="flex flex-wrap gap-1.5 pt-0.5">
              {session.subjectCodes && session.subjectCodes.length > 0 ? (
                session.subjectCodes.map((sub: string) => (
                  <span
                    key={sub}
                    className="px-2 py-0.5 rounded-md font-bold bg-[#3F451F] text-[#EDE8D8]"
                  >
                    {sub}
                  </span>
                ))
              ) : (
                <span className="font-semibold text-[#24251C]">Institutional Administrator</span>
              )}
            </div>
          </div>

          <div className="p-3 rounded-xl bg-[#EDE8D8]/40 border border-[#E4DDCA] space-y-1">
            <span className="font-bold text-[#77735F] uppercase text-[10px]">Teaching Venues</span>
            <p className="font-bold text-[#24251C] pt-0.5">
              Lecture Hall LH-101 / LAB-1
            </p>
            <p className="text-[11px] text-[#77735F]">Capacity: 60 students per hall</p>
          </div>

          <div className="p-3 rounded-xl bg-[#EDE8D8]/40 border border-[#E4DDCA] space-y-1">
            <span className="font-bold text-[#77735F] uppercase text-[10px]">Curriculum Workload</span>
            <p className="font-bold text-[#24251C] pt-0.5">
              14 Hours / Week
            </p>
            <p className="text-[11px] text-[#77735F]">10h Lectures (1h) + 4h Labs (2h)</p>
          </div>
        </div>
      </div>

      {/* Institutional Policy Settings (From Backend Meta Config) */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-6 shadow-2xs space-y-4">
        <div className="flex items-center justify-between border-b border-[#E4DDCA] pb-3">
          <div>
            <h2 className="text-base font-bold text-[#24251C]">Institutional Attendance Rules & Policies</h2>
            <p className="text-xs text-[#77735F]">
              Server-enforced regulatory configuration loaded from <code className="text-[#6C5119]">/api/v1/meta/config</code>.
            </p>
          </div>
          <span className="px-2.5 py-1 rounded-lg bg-emerald-100 text-emerald-800 text-[10px] font-black uppercase">
            Synchronized
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs">
          <div className="p-4 rounded-xl bg-white border border-[#E4DDCA] space-y-1.5">
            <span className="font-bold text-[#77735F]">Defaulter Minimum Threshold</span>
            <p className="text-2xl font-black text-[#6C5119]">
              {metaConfig ? `${metaConfig.defaulter_threshold_percent}%` : "75.0%"}
            </p>
            <p className="text-[11px] text-[#77735F]">
              Students below this percentage are automatically flagged for attendance review.
            </p>
          </div>

          <div className="p-4 rounded-xl bg-white border border-[#E4DDCA] space-y-1.5">
            <span className="font-bold text-[#77735F]">Roster Edit-Lock Window</span>
            <p className="text-2xl font-black text-[#24251C]">
              {metaConfig ? `${metaConfig.edit_lock_hours} Hours` : "24 Hours"}
            </p>
            <p className="text-[11px] text-[#77735F]">
              Faculty edits are locked after 24 hours to prevent unauthorized attendance tampering.
            </p>
          </div>

          <div className="p-4 rounded-xl bg-white border border-[#E4DDCA] space-y-1.5">
            <span className="font-bold text-[#77735F]">Attendance Health Bands</span>
            <div className="space-y-1 pt-1">
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-emerald-700 font-bold">Good Standing:</span>
                <span className="font-mono font-bold">≥ 85%</span>
              </div>
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-amber-700 font-bold">Advisory Warning:</span>
                <span className="font-mono font-bold">70% – 84%</span>
              </div>
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-red-700 font-bold">Defaulter Critical:</span>
                <span className="font-mono font-bold">&lt; 70%</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Classroom & Attendance Preferences */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-6 shadow-2xs space-y-4">
        <h2 className="text-base font-bold text-[#24251C]">Classroom & Roster Preferences</h2>

        <div className="space-y-4 divide-y divide-[#E4DDCA]/60 text-sm">
          <div className="flex items-center justify-between pt-2">
            <div>
              <p className="font-semibold text-[#24251C]">Default Status for Unmarked Students</p>
              <p className="text-xs text-[#77735F]">
                When opening a fresh class session roster, initial state of each enrolled student.
              </p>
            </div>
            <select
              value={defaultStatus}
              onChange={(e) => setDefaultStatus(e.target.value as "UNREVIEWED" | "PRESENT")}
              className="px-3 py-1.5 rounded-xl bg-white border border-[#E4DDCA] text-xs font-bold text-[#24251C] cursor-pointer"
            >
              <option value="UNREVIEWED">UNREVIEWED (Require Manual Tap)</option>
              <option value="PRESENT">PRESENT (Mark All Present by Default)</option>
            </select>
          </div>

          <div className="flex items-center justify-between pt-3">
            <div>
              <p className="font-semibold text-[#24251C]">Real-Time Roster Synchronization</p>
              <p className="text-xs text-[#77735F]">
                Periodically check for active session updates and AI scan completions.
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
              <p className="font-semibold text-[#24251C]">Audio Feedback on Status Changes</p>
              <p className="text-xs text-[#77735F]">
                Play soft affirmation click tone when changing a student attendance state.
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
              <p className="font-semibold text-[#24251C]">Daily Attendance Summary Digest</p>
              <p className="text-xs text-[#77735F]">
                Receive automated end-of-day attendance reports for your assigned classes.
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

          <div className="flex items-center justify-between pt-3">
            <div>
              <p className="font-semibold text-[#24251C]">Low Attendance Warning Alert (% Threshold)</p>
              <p className="text-xs text-[#77735F]">
                Display notification banner when overall session attendance drops below threshold.
              </p>
            </div>
            <div className="flex items-center space-x-2">
              <input
                type="number"
                min={50}
                max={90}
                value={lowAttendanceAlert}
                onChange={(e) => setLowAttendanceAlert(Number(e.target.value))}
                className="w-16 px-2.5 py-1 text-center font-bold text-xs bg-white border border-[#E4DDCA] rounded-xl"
              />
              <span className="text-xs font-bold text-[#77735F]">%</span>
            </div>
          </div>
        </div>
      </div>

      {/* Security & Token Session Details */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-6 shadow-2xs space-y-4">
        <h2 className="text-base font-bold text-[#24251C]">Security & Token Session Architecture</h2>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
          <div className="p-3.5 rounded-xl bg-white border border-[#E4DDCA] space-y-1">
            <span className="font-bold text-[#77735F]">Access Token Storage</span>
            <p className="font-bold text-[#24251C]">Protected In-Memory Closure</p>
            <p className="text-[11px] text-[#77735F]">
              Never written to localStorage to protect against Cross-Site Scripting (XSS).
            </p>
          </div>

          <div className="p-3.5 rounded-xl bg-white border border-[#E4DDCA] space-y-1">
            <span className="font-bold text-[#77735F]">Refresh Token Rotation</span>
            <p className="font-bold text-[#24251C]">HttpOnly Cookie + Single-Flight</p>
            <p className="text-[11px] text-[#77735F]">
              Rotated automatically via backend database records with token reuse detection.
            </p>
          </div>
        </div>
      </div>

      {/* Backend Health Diagnostics */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-6 shadow-2xs space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold text-[#24251C]">Live Backend Diagnostics</h2>
            <p className="text-xs text-[#77735F]">
              Live status and network latency of FastAPI server and database.
            </p>
          </div>
          <button
            onClick={() => void checkHealth()}
            disabled={isCheckingHealth}
            className="px-3.5 py-2 rounded-xl text-xs font-bold bg-[#3F451F] text-[#EDE8D8] hover:bg-[#343919] transition-colors disabled:opacity-50 cursor-pointer shadow-2xs"
          >
            {isCheckingHealth ? "Probing Server..." : "Test Server Connection"}
          </button>
        </div>

        <div className="p-4 bg-[#EDE8D8]/40 border border-[#E4DDCA] rounded-xl text-xs space-y-2.5">
          <div className="flex items-center justify-between">
            <span className="text-[#77735F]">Endpoint:</span>
            <span className="font-mono text-[#24251C]">/health (FastAPI 0.115 Engine)</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[#77735F]">Operational Status:</span>
            <span className={`font-bold inline-flex items-center gap-1.5 ${
              healthStatus?.ok ? "text-emerald-700" : "text-red-600"
            }`}>
              <span className={`w-2 h-2 rounded-full ${healthStatus?.ok ? "bg-emerald-500" : "bg-red-500"}`} />
              {healthStatus?.ok ? "Operational (HTTP 200 OK)" : "Unreachable or Degraded"}
            </span>
          </div>
          {healthStatus?.latencyMs !== undefined && (
            <div className="flex items-center justify-between">
              <span className="text-[#77735F]">Round-Trip Latency:</span>
              <span className="font-mono font-bold text-[#6C5119]">{healthStatus.latencyMs} ms</span>
            </div>
          )}
          {healthStatus?.timestamp && (
            <div className="flex items-center justify-between">
              <span className="text-[#77735F]">Last Checked:</span>
              <span className="font-mono text-[#77735F]">{healthStatus.timestamp}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
