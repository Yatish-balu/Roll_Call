import React, { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  fetchAttendanceUnlockRequests,
  reviewAttendanceUnlockRequest,
  type AttendanceUnlockRequest,
} from "@/services/api/attendance";

interface PendingUnlockRequestsBannerProps {
  isAdmin: boolean;
}

export function PendingUnlockRequestsBanner({ isAdmin }: PendingUnlockRequestsBannerProps) {
  const navigate = useNavigate();
  const [requests, setRequests] = useState<AttendanceUnlockRequest[]>([]);
  const [_isLoading, setIsLoading] = useState(false);
  const [processingId, setProcessingId] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const loadRequests = useCallback(async () => {
    if (!isAdmin) return;
    setIsLoading(true);
    try {
      const data = await fetchAttendanceUnlockRequests({ status: "PENDING" });
      setRequests(data || []);
    } catch {
      setRequests([]);
    } finally {
      setIsLoading(false);
    }
  }, [isAdmin]);

  useEffect(() => {
    void loadRequests();

    const handleSync = () => {
      void loadRequests();
    };
    window.addEventListener("rollcall-unlock-request-updated", handleSync);
    return () => {
      window.removeEventListener("rollcall-unlock-request-updated", handleSync);
    };
  }, [loadRequests]);

  const handleReview = async (
    requestId: string,
    decision: "APPROVED" | "REJECTED",
    teacherName: string
  ) => {
    setProcessingId(requestId);
    setStatusMessage(null);
    try {
      await reviewAttendanceUnlockRequest(requestId, {
        decision,
        unlock_hours: 24,
        admin_notes: decision === "APPROVED" ? "Approved from Admin Dashboard" : "Rejected from Admin Dashboard",
      });
      setStatusMessage({
        type: "success",
        text:
          decision === "APPROVED"
            ? `Permission granted to ${teacherName}. Session attendance is unlocked for 24 hours.`
            : `Permission request from ${teacherName} rejected.`,
      });
      window.dispatchEvent(new CustomEvent("rollcall-unlock-request-updated"));
      window.dispatchEvent(new CustomEvent("rollcall-attendance-updated"));
      await loadRequests();
    } catch (err: unknown) {
      setStatusMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Failed to review request.",
      });
    } finally {
      setProcessingId(null);
    }
  };

  if (!isAdmin || requests.length === 0) {
    return null;
  }

  return (
    <div className="bg-amber-50/90 border-2 border-amber-300 rounded-2xl p-4 sm:p-5 shadow-sm space-y-3.5 animate-in fade-in duration-200">
      <div className="flex items-center justify-between gap-3 flex-wrap border-b border-amber-200/80 pb-3">
        <div className="flex items-center space-x-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-500 text-white font-black text-lg shadow-xs">
            🔔
          </span>
          <div>
            <div className="flex items-center space-x-2">
              <h3 className="font-black text-sm sm:text-base text-amber-950">
                Action Required: Teacher Attendance Permission Requests
              </h3>
              <span className="px-2 py-0.5 rounded-full text-[11px] font-black bg-amber-600 text-white shadow-2xs">
                {requests.length} Pending
              </span>
            </div>
            <p className="text-xs text-amber-900/80 mt-0.5">
              Teachers have requested administrative override to correct attendance records older than 24 hours.
            </p>
          </div>
        </div>
      </div>

      {statusMessage && (
        <div
          className={`p-3 rounded-xl text-xs font-semibold ${
            statusMessage.type === "success"
              ? "bg-emerald-100 border border-emerald-300 text-emerald-900"
              : "bg-rose-100 border border-rose-300 text-rose-900"
          }`}
        >
          {statusMessage.text}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5 pt-1">
        {requests.map((req) => (
          <div
            key={req.request_id}
            className="bg-white rounded-xl border border-amber-200 p-4 shadow-2xs flex flex-col justify-between space-y-3 hover:border-amber-400 transition-colors"
          >
            <div className="space-y-2">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <span className="text-[11px] font-extrabold uppercase tracking-wider text-amber-800">
                    {req.subject_code || "Class Session"} · {req.session_date || "Date Unspecified"}
                  </span>
                  <h4 className="font-bold text-sm text-[#24251C]">
                    {req.teacher_name || req.teacher_id}
                  </h4>
                  {req.teacher_email && (
                    <span className="text-[11px] text-[#77735F]">{req.teacher_email}</span>
                  )}
                </div>
                <span className="text-[10px] font-semibold text-[#77735F] bg-stone-100 px-2 py-0.5 rounded-md whitespace-nowrap">
                  {req.created_at ? req.created_at.slice(0, 10) : "Pending"}
                </span>
              </div>

              <div className="bg-[#FBF8F0] p-2.5 rounded-lg border border-[#E4DDCA]/60 text-xs text-[#24251C]">
                <span className="font-bold text-[#6C5119]">Teacher's Justification: </span>
                <span className="italic">"{req.reason}"</span>
                {req.target_usns && (
                  <div className="mt-1 text-[11px] text-[#77735F]">
                    <span className="font-bold text-[#3F451F]">Target Student USN: </span>
                    {req.target_usns}
                  </div>
                )}
                {req.requested_change && (
                  <div className="mt-0.5 text-[11px] text-[#77735F]">
                    <span className="font-bold text-[#3F451F]">Requested Change: </span>
                    {req.requested_change}
                  </div>
                )}
              </div>
            </div>

            <div className="pt-2 border-t border-stone-100 flex items-center justify-between gap-2 flex-wrap">
              <div className="flex items-center space-x-2">
                <button
                  type="button"
                  disabled={processingId === req.request_id}
                  onClick={() => handleReview(req.request_id, "APPROVED", req.teacher_name || req.teacher_id)}
                  className="px-3.5 py-1.5 rounded-xl bg-emerald-700 hover:bg-emerald-800 text-white font-bold text-xs shadow-xs transition-all cursor-pointer disabled:opacity-50"
                >
                  {processingId === req.request_id ? "Processing..." : "✅ Approve (24h)"}
                </button>
                <button
                  type="button"
                  disabled={processingId === req.request_id}
                  onClick={() => handleReview(req.request_id, "REJECTED", req.teacher_name || req.teacher_id)}
                  className="px-3.5 py-1.5 rounded-xl bg-stone-200 hover:bg-rose-100 text-stone-700 hover:text-rose-800 font-bold text-xs transition-all cursor-pointer disabled:opacity-50"
                >
                  ❌ Reject
                </button>
              </div>

              <button
                type="button"
                onClick={() => navigate(`/attendance?sessionId=${encodeURIComponent(req.session_id)}`)}
                className="text-xs font-bold text-[#6C5119] hover:underline cursor-pointer ml-auto"
              >
                Inspect Session Roster →
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

