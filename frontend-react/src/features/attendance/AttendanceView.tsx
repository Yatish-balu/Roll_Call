"use client";

import React, { useEffect, useState, useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import {
  fetchSessionAllocations,
  fetchSessions,
  type SessionAllocation,
  type SessionItem,
} from "@/services/api/sessions";
import { fetchStudents } from "@/services/api/students";
import { useAuth } from "@/hooks/useAuth";
import {
  fetchSessionAttendance,
  updateSessionAttendance,
  reconcileAttendance,
  type AttendanceRecord,
  type AttendanceStatus,
} from "@/services/api/attendance";
import { useResource } from "@/hooks/useResource";
import { invalidate, mutateCache } from "@/services/api/cache";

const SESSIONS_LIST_KEY = "/api/v1/sessions?limit=50";
const SESSIONS_ALLOCATIONS_KEY = "/api/v1/sessions/allocations";

export function AttendanceView() {
  const [searchParams] = useSearchParams();
  const querySession = searchParams.get("session") || searchParams.get("sessionId") || "";
  const { session, isAdmin, isFaculty, isViewer, canMarkAttendance } = useAuth();

  const sessionsRes = useResource<{ items?: SessionItem[]; total?: number }>(
    SESSIONS_LIST_KEY,
    () => fetchSessions({ limit: 50 })
  );
  const allocationsRes = useResource<{ items?: SessionAllocation[]; total?: number }>(
    SESSIONS_ALLOCATIONS_KEY,
    () => fetchSessionAllocations().catch(() => ({ items: [] as SessionAllocation[], total: 0 }))
  );

  const sessions = useMemo(() => sessionsRes.data?.items ?? [], [sessionsRes.data]);
  const allocations = useMemo(() => allocationsRes.data?.items ?? [], [allocationsRes.data]);
  const isLoadingSessions = sessionsRes.isLoading && !sessionsRes.data;

  const [selectedSessionId, setSelectedSessionId] = useState<string>(querySession);

  // Auto-select initial session
  useEffect(() => {
    if (querySession) {
      setSelectedSessionId(querySession);
    } else if (!selectedSessionId && sessions.length > 0) {
      setSelectedSessionId(sessions[0].session_id);
    }
  }, [querySession, selectedSessionId, sessions]);

  const attendanceKey = selectedSessionId
    ? `/api/v1/attendance/sessions/${selectedSessionId}`
    : null;

  const attendanceRes = useResource<AttendanceRecord[]>(
    attendanceKey,
    () => fetchSessionAttendance(selectedSessionId!)
  );

  const [attendanceRecords, setAttendanceRecords] = useState<AttendanceRecord[]>([]);
  const [initialAttendanceRecords, setInitialAttendanceRecords] = useState<AttendanceRecord[]>([]);

  useEffect(() => {
    if (attendanceRes.data) {
      setAttendanceRecords(attendanceRes.data);
      setInitialAttendanceRecords(attendanceRes.data);
    }
  }, [attendanceRes.data]);

  // Dirty count computation for smart save state
  const dirtyCount = useMemo(() => {
    if (initialAttendanceRecords.length === 0 && attendanceRecords.length > 0) {
      return attendanceRecords.length;
    }
    const initialMap = new Map<string, string>();
    initialAttendanceRecords.forEach((r) => initialMap.set(r.usn, r.status));
    let changed = 0;
    attendanceRecords.forEach((r) => {
      if (initialMap.get(r.usn) !== r.status) {
        changed++;
      }
    });
    return changed;
  }, [attendanceRecords, initialAttendanceRecords]);

  const isLoadingAttendance = attendanceRes.isLoading && !attendanceRes.data;
  const [isSaving, setIsSaving] = useState(false);
  const [statusMessage, setStatusMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // Reconciliation modal state
  const [reconcileTarget, setReconcileTarget] = useState<AttendanceRecord | null>(null);
  const [reconcileStatus, setReconcileStatus] = useState<AttendanceStatus>("PRESENT");
  const [isReconciling, setIsReconciling] = useState(false);

  // Filter state
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("ALL");

  const formatApiError = (err: unknown): string => {
    if (err && typeof err === "object" && "statusCode" in err) {
      const apiErr = err as { statusCode: number; message: string };
      if (apiErr.statusCode === 401) {
        return "Authentication expired. Please sign in again.";
      }
      if (apiErr.statusCode === 403) {
        return `Access Forbidden (403): ${apiErr.message || "You are not authorized to edit attendance for this session."}`;
      }
      if (apiErr.statusCode === 404) {
        return `Not Found (404): ${apiErr.message || "Session or student record does not exist on the server."}`;
      }
      if (apiErr.statusCode === 409) {
        return `Conflict (409): ${apiErr.message || "Duplicate attendance records or concurrent edit detected."}`;
      }
      if (apiErr.statusCode === 422) {
        return `Validation Error (422): ${apiErr.message || "Invalid payload format or status parameters."}`;
      }
      return apiErr.message || "Failed to update attendance on server.";
    }
    return err instanceof Error ? err.message : "Failed to load or update attendance records.";
  };

  useEffect(() => {
    if (sessionsRes.error) {
      setStatusMessage({
        type: "error",
        text: formatApiError(sessionsRes.error),
      });
    }
  }, [sessionsRes.error]);

  useEffect(() => {
    if (attendanceRes.error) {
      setStatusMessage({
        type: "error",
        text: formatApiError(attendanceRes.error),
      });
    }
  }, [attendanceRes.error]);

  const _loadAttendance = useCallback(async (_sessionId?: string) => {
    await attendanceRes.refresh();
  }, [attendanceRes]);

  // Selected session object
  const activeSession = useMemo(() => {
    return sessions.find((s) => s.session_id === selectedSessionId) || null;
  }, [sessions, selectedSessionId]);

  // Real class slot of the selected session (room, batch and time window).
  const sessionAllocations = useMemo(
    () => allocations.filter((allocation) => allocation.session_id === selectedSessionId),
    [allocations, selectedSessionId]
  );
  const sessionRooms = useMemo(
    () =>
      Array.from(
        new Set(
          sessionAllocations
            .map((allocation) => allocation.room_id)
            .filter((room): room is string => Boolean(room))
        )
      ),
    [sessionAllocations]
  );
  const sessionBatches = useMemo(
    () =>
      Array.from(
        new Set(
          sessionAllocations
            .map((allocation) => allocation.batch_id)
            .filter((batch): batch is string => Boolean(batch))
        )
      ),
    [sessionAllocations]
  );
  const sessionSlot = sessionAllocations[0] ?? null;
  const sessionRoom = sessionRooms[0] ?? "";

  // Attendance counts
  const counts = useMemo(() => {
    let present = 0;
    let absent = 0;
    let pending = 0;
    let unreviewed = 0;

    attendanceRecords.forEach((r) => {
      if (r.status === "PRESENT") present++;
      else if (r.status === "ABSENT") absent++;
      else if (r.status === "PENDING") pending++;
      else if (r.status === "UNREVIEWED") unreviewed++;
    });

    return {
      present,
      absent,
      pending,
      unreviewed,
      total: attendanceRecords.length,
    };
  }, [attendanceRecords]);

  // Status toggle handler
  const handleStatusChange = (usn: string, nextStatus: AttendanceStatus) => {
    if (!canMarkAttendance) {
      setStatusMessage({
        type: "error",
        text: "Read-only access: Viewers cannot modify attendance records.",
      });
      return;
    }
    setAttendanceRecords((prev) =>
      prev.map((rec) => (rec.usn === usn ? { ...rec, status: nextStatus } : rec))
    );
  };

  const [isInitializing, setIsInitializing] = useState(false);

  // Initialize roster from enrolled students
  const handleInitializeRoster = async () => {
    if (!canMarkAttendance || !selectedSessionId || isInitializing) return;
    setIsInitializing(true);
    setStatusMessage(null);
    try {
      const studentRes = await fetchStudents({ limit: 50 });
      const students = studentRes.items || [];
      const newRecords: AttendanceRecord[] = students.map((s) => ({
        session_id: selectedSessionId,
        usn: s.usn,
        student_name: s.name,
        branch: s.branch,
        status: "UNREVIEWED",
        room_id: sessionRoom || "UNALLOCATED",
        source: "manual",
      }));
      setAttendanceRecords(newRecords);
      setStatusMessage({
        type: "success",
        text: `Loaded ${students.length} students into roster. Update status marks and click "Save Changes" to commit.`,
      });
    } catch (err: unknown) {
      setStatusMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Failed to load students.",
      });
    } finally {
      setIsInitializing(false);
    }
  };

  // Mark all present
  const handleMarkAllPresent = () => {
    if (!canMarkAttendance) return;
    setAttendanceRecords((prev) =>
      prev.map((rec) => ({ ...rec, status: "PRESENT" }))
    );
    setStatusMessage({
      type: "success",
      text: "All students marked PRESENT. Remember to save changes.",
    });
  };

  // Save changes to backend
  const handleSaveChanges = async () => {
    if (!canMarkAttendance || !selectedSessionId || isSaving) return;
    setIsSaving(true);
    setStatusMessage(null);

    try {
      const payload = attendanceRecords.map((r) => ({
        usn: r.usn,
        room_id: r.room_id || sessionRoom || "UNALLOCATED",
        status: r.status,
      }));
      const res = await updateSessionAttendance(selectedSessionId, payload);
      setStatusMessage({
        type: "success",
        text: res.message || `Successfully synchronized ${payload.length} attendance marks for session '${selectedSessionId}'.`,
      });
      setInitialAttendanceRecords([...attendanceRecords]);
      // Update cache immediately and invalidate dependent queries
      if (attendanceKey) {
        mutateCache(attendanceKey, attendanceRecords);
      }
      invalidate([
        `/api/v1/attendance/sessions/${selectedSessionId}`,
        "dashboard",
        "calendar",
        "analytics",
      ]);
      // Let other views (calendar, sessions) know that the attendance changed.
      window.dispatchEvent(
        new CustomEvent("rollcall:attendance-changed", {
          detail: { session_id: selectedSessionId },
        })
      );
    } catch (err: unknown) {
      setStatusMessage({
        type: "error",
        text: formatApiError(err),
      });
    } finally {
      setIsSaving(false);
    }
  };

  // Submit reconciliation
  const handleReconcileSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canMarkAttendance || !reconcileTarget || !selectedSessionId) return;
    setIsReconciling(true);

    try {
      await reconcileAttendance(selectedSessionId, {
        usn: reconcileTarget.usn,
        resolved_status: reconcileStatus,
      });
      // Update local state
      const updated = attendanceRecords.map((r) =>
        r.usn === reconcileTarget.usn ? { ...r, status: reconcileStatus } : r
      );
      setAttendanceRecords(updated);
      if (attendanceKey) {
        mutateCache(attendanceKey, updated);
      }
      invalidate([
        `/api/v1/attendance/sessions/${selectedSessionId}`,
        "dashboard",
        "calendar",
        "analytics",
      ]);
      setReconcileTarget(null);
      setStatusMessage({
        type: "success",
        text: `Reconciliation confirmed for ${reconcileTarget.usn}.`,
      });
    } catch (err: unknown) {
      setStatusMessage({
        type: "error",
        text: formatApiError(err),
      });
    } finally {
      setIsReconciling(false);
    }
  };

  // Filtered records
  const filteredRecords = useMemo(() => {
    return attendanceRecords.filter((rec) => {
      const matchesSearch =
        rec.usn.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (rec.student_name && rec.student_name.toLowerCase().includes(searchQuery.toLowerCase()));
      const matchesStatus = statusFilter === "ALL" || rec.status === statusFilter;
      return matchesSearch && matchesStatus;
    });
  }, [attendanceRecords, searchQuery, statusFilter]);

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-2">
        <div>
          <div className="flex items-center space-x-2.5 flex-wrap gap-y-1">
            <h1 className="text-2xl sm:text-3xl font-extrabold text-[#24251C] tracking-tight">
              Attendance Verification
            </h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-[#EDE8D8] text-[#6C5119] border border-[#E4DDCA]">
              {isLoadingAttendance ? "..." : `${attendanceRecords.length} Students`}
            </span>
            {isViewer && (
              <span className="px-3 py-1 rounded-xl bg-slate-100 text-slate-700 border border-slate-300 text-xs font-bold flex items-center space-x-1.5 shadow-2xs">
                <svg className="w-3.5 h-3.5 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                </svg>
                <span>Read-Only Viewer</span>
              </span>
            )}
            {!isAdmin && isFaculty && session.subjectCodes && session.subjectCodes.length > 0 && (
              <span className="px-2.5 py-0.5 rounded-lg bg-[#EDE8D8] text-[#6C5119] border border-[#E4DDCA] text-xs font-semibold">
                Scope: {session.subjectCodes.join(", ")}
              </span>
            )}
          </div>
          <p className="text-xs sm:text-sm text-[#77735F] mt-1">
            Session allocation roster, multi-modal mark reconciliation, and institutional review.
          </p>
        </div>

        {canMarkAttendance ? (
          <div className="flex items-center space-x-2.5">
            <button
              onClick={handleMarkAllPresent}
              disabled={attendanceRecords.length === 0 || isLoadingAttendance}
              className="px-3.5 py-2 rounded-xl text-xs font-bold bg-[#EDE8D8] text-[#24251C] hover:bg-[#E4DDCA] border border-[#E4DDCA] transition-colors disabled:opacity-50 cursor-pointer"
            >
              Mark All Present
            </button>
            <button
              onClick={() => void handleSaveChanges()}
              disabled={attendanceRecords.length === 0 || isSaving || isLoadingAttendance || dirtyCount === 0}
              className={`inline-flex items-center space-x-2 px-4 py-2 rounded-xl text-xs sm:text-sm font-bold transition-all shadow-2xs ${
                dirtyCount > 0
                  ? "bg-[#6C5119] hover:bg-[#594214] text-white cursor-pointer ring-2 ring-[#B6892C]/40"
                  : "bg-[#EDE8D8] text-[#77735F] border border-[#E4DDCA] cursor-not-allowed opacity-60"
              }`}
            >
              {isSaving ? (
                <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : (
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.2} d="M5 13l4 4L19 7" />
                </svg>
              )}
              <span>{isSaving ? "Saving..." : dirtyCount > 0 ? `Save Changes (${dirtyCount})` : "Save Changes"}</span>
            </button>
          </div>
        ) : (
          <span className="px-3.5 py-2 rounded-xl bg-slate-100 text-slate-600 text-xs font-semibold border border-slate-200">
            Attendance Modification Restricted (Viewer)
          </span>
        )}
      </div>

      {/* Status Notifications */}
      {statusMessage && (
        <div
          className={`p-3.5 rounded-xl border text-xs flex items-center justify-between ${
            statusMessage.type === "success"
              ? "bg-emerald-50 border-emerald-200 text-emerald-900"
              : "bg-rose-50 border-rose-200 text-rose-900"
          }`}
        >
          <span>{statusMessage.text}</span>
          <button
            onClick={() => setStatusMessage(null)}
            className="font-bold ml-4 cursor-pointer"
          >
            ✕
          </button>
        </div>
      )}

      {/* Compact Session Selection & Metadata Toolbar */}
      <div className="card-crisp bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-3.5 sm:p-4 shadow-2xs">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
          {/* Session Selector */}
          <div className="flex items-center space-x-2.5 w-full lg:w-auto flex-1 max-w-xl">
            <span className="text-xs font-bold text-[#77735F] uppercase tracking-wider shrink-0">
              Session:
            </span>
            <select
              value={selectedSessionId}
              onChange={(e) => setSelectedSessionId(e.target.value)}
              disabled={isLoadingSessions}
              className="w-full px-3 py-1.5 rounded-xl bg-white border border-[#E4DDCA] text-xs sm:text-sm font-semibold text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119] cursor-pointer"
            >
              {isLoadingSessions && <option>Loading sessions...</option>}
              {!isLoadingSessions && sessions.length === 0 && (
                <option>No academic sessions found</option>
              )}
              {sessions.map((s) => (
                <option key={s.session_id} value={s.session_id}>
                  {s.subject_code ? `[${s.subject_code}] ` : ""}
                  {s.subject} ({s.date}) — ID: {s.session_id}
                </option>
              ))}
            </select>
          </div>

          {/* Clean Inline Metadata Pairs */}
          {activeSession && (
            <div className="flex flex-wrap items-center gap-x-3.5 gap-y-1 text-xs text-[#77735F] lg:border-l lg:border-[#E4DDCA] lg:pl-4">
              <span className="inline-flex items-center space-x-1 font-bold text-[#24251C]">
                <span>📚</span>
                <span>{activeSession.subject}</span>
              </span>
              <span>•</span>
              <span className="inline-flex items-center space-x-1 font-medium">
                <span>📅</span>
                <span>{activeSession.date}</span>
              </span>
              <span>•</span>
              <span className="inline-flex items-center space-x-1 font-medium">
                <span>🏛️</span>
                <span>{sessionRooms.length > 0 ? sessionRooms.join(", ") : "Not allocated"}</span>
              </span>
              <span>•</span>
              <span className="inline-flex items-center space-x-1 font-medium">
                <span>🕒</span>
                <span>
                  {sessionSlot
                    ? `${sessionSlot.start_time} - ${sessionSlot.end_time}`
                    : "Not scheduled"}
                  {sessionBatches.length > 0 ? ` (Batch ${sessionBatches.join(", ")})` : ""}
                </span>
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Interactive KPI Filter Cards (56px Sleek Stat Cards with active ring) */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {/* PRESENT */}
        <button
          type="button"
          onClick={() => setStatusFilter((prev) => (prev === "PRESENT" ? "ALL" : "PRESENT"))}
          className={`h-14 rounded-xl border p-2.5 flex items-center justify-between transition-all cursor-pointer text-left ${
            statusFilter === "PRESENT"
              ? "bg-[#E8F5E9] border-[#2E7D32] ring-2 ring-[#2E7D32]/30 shadow-xs"
              : "bg-[#E8F5E9]/60 hover:bg-[#E8F5E9] border-[#C8E6C9]"
          }`}
        >
          <div className="flex items-center space-x-2">
            <span className="w-2.5 h-2.5 rounded-full bg-[#2E7D32]" />
            <span className="text-xs font-bold text-[#2E7D32] uppercase">Present</span>
          </div>
          <p className="text-xl font-black text-[#1B5E20]">{counts.present}</p>
        </button>

        {/* ABSENT */}
        <button
          type="button"
          onClick={() => setStatusFilter((prev) => (prev === "ABSENT" ? "ALL" : "ABSENT"))}
          className={`h-14 rounded-xl border p-2.5 flex items-center justify-between transition-all cursor-pointer text-left ${
            statusFilter === "ABSENT"
              ? "bg-[#FFEBEE] border-[#C62828] ring-2 ring-[#C62828]/30 shadow-xs"
              : "bg-[#FFEBEE]/60 hover:bg-[#FFEBEE] border-[#FFCDD2]"
          }`}
        >
          <div className="flex items-center space-x-2">
            <span className="w-2.5 h-2.5 rounded-full bg-[#C62828]" />
            <span className="text-xs font-bold text-[#C62828] uppercase">Absent</span>
          </div>
          <p className="text-xl font-black text-[#B71C1C]">{counts.absent}</p>
        </button>

        {/* PENDING */}
        <button
          type="button"
          onClick={() => setStatusFilter((prev) => (prev === "PENDING" ? "ALL" : "PENDING"))}
          className={`h-14 rounded-xl border p-2.5 flex items-center justify-between transition-all cursor-pointer text-left ${
            statusFilter === "PENDING"
              ? "bg-[#FFF8E1] border-[#F57F17] ring-2 ring-[#F57F17]/30 shadow-xs"
              : "bg-[#FFF8E1]/60 hover:bg-[#FFF8E1] border-[#FFE082]"
          }`}
        >
          <div className="flex items-center space-x-2">
            <span className="w-2.5 h-2.5 rounded-full bg-[#F57F17]" />
            <span className="text-xs font-bold text-[#F57F17] uppercase">Pending</span>
          </div>
          <p className="text-xl font-black text-[#E65100]">{counts.pending}</p>
        </button>

        {/* UNREVIEWED */}
        <button
          type="button"
          onClick={() => setStatusFilter((prev) => (prev === "UNREVIEWED" ? "ALL" : "UNREVIEWED"))}
          className={`h-14 rounded-xl border p-2.5 flex items-center justify-between transition-all cursor-pointer text-left ${
            statusFilter === "UNREVIEWED"
              ? "bg-[#EDE8D8] border-[#72785E] ring-2 ring-[#72785E]/30 shadow-xs"
              : "bg-[#EDE8D8]/60 hover:bg-[#EDE8D8] border-[#DCD5BE]"
          }`}
        >
          <div className="flex items-center space-x-2">
            <span className="w-2.5 h-2.5 rounded-full bg-[#72785E]" />
            <span className="text-xs font-bold text-[#72785E] uppercase">Unreviewed</span>
          </div>
          <p className="text-xl font-black text-[#3F451F]">{counts.unreviewed}</p>
        </button>
      </div>

      {/* Student Roster Table Card with Embedded Search */}
      <div className="card-crisp bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl shadow-2xs overflow-hidden">
        {/* Card Header Toolbar with Embedded Search */}
        <div className="p-3.5 sm:p-4 border-b border-[#E4DDCA] bg-[#EDE8D8]/30 flex flex-col sm:flex-row items-center justify-between gap-3">
          <div className="flex items-center space-x-2 w-full sm:w-auto">
            <span className="text-xs font-bold text-[#24251C] uppercase tracking-wider">
              Student Roster
            </span>
            <span className="text-xs font-semibold text-[#77735F]">
              ({filteredRecords.length} of {attendanceRecords.length})
            </span>
            {statusFilter !== "ALL" && (
              <button
                type="button"
                onClick={() => setStatusFilter("ALL")}
                className="ml-2 text-[11px] font-bold text-[#6C5119] hover:underline cursor-pointer"
              >
                Clear filter
              </button>
            )}
          </div>

          <div className="relative w-full sm:w-80">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Filter roster by USN or student name..."
              className="w-full pl-8 pr-3 py-1.5 rounded-xl bg-white border border-[#E4DDCA] text-xs sm:text-sm text-[#24251C] placeholder-[#77735F]/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
            />
            <svg
              className="w-4 h-4 text-[#77735F] absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs sm:text-sm">
            <thead>
              <tr className="border-b border-[#E4DDCA] bg-[#EDE8D8]/50 text-[#77735F] font-semibold">
                <th className="py-3 pl-4 sm:pl-6">USN</th>
                <th className="py-3 px-4">Student Name</th>
                <th className="py-3 px-4">Room Allocation</th>
                <th className="py-3 px-4">Attendance Status</th>
                <th className="py-3 pr-4 sm:pr-6 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#E4DDCA]/60 text-[#24251C]">
              {isLoadingAttendance && (
                <tr>
                  <td colSpan={5} className="py-12 text-center text-[#77735F]">
                    <div className="flex flex-col items-center space-y-2">
                      <div className="w-6 h-6 border-2 border-[#6C5119] border-t-transparent rounded-full animate-spin" />
                      <span>Loading session roster records...</span>
                    </div>
                  </td>
                </tr>
              )}

              {!isLoadingAttendance && filteredRecords.length === 0 && (
                <tr>
                  <td colSpan={5} className="py-14 text-center">
                    <div className="max-w-xs mx-auto space-y-3 text-[#77735F]">
                      <svg className="w-10 h-10 mx-auto opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                      </svg>
                      <p className="font-bold text-[#24251C]">No Attendance Marks Recorded</p>
                      <p className="text-xs">No students have attendance entries recorded for this session yet.</p>
                      <button
                        type="button"
                        onClick={handleInitializeRoster}
                        disabled={isInitializing}
                        className="px-4 py-2 rounded-xl bg-[#3F451F] text-[#EDE8D8] text-xs font-bold hover:bg-[#343919] transition-colors shadow-2xs cursor-pointer disabled:opacity-50"
                      >
                        {isInitializing ? "Loading Students..." : "Initialize Roster from Students"}
                      </button>
                    </div>
                  </td>
                </tr>
              )}

              {!isLoadingAttendance &&
                filteredRecords.map((rec) => {
                  return (
                    <tr key={rec.usn} className="group hover:bg-[#EDE8D8]/25 transition-colors">
                      <td className="py-3 pl-4 sm:pl-6 font-bold text-[#6C5119] [font-variant-numeric:tabular-nums]">
                        {rec.usn}
                      </td>
                      <td className="py-3 px-4 font-semibold text-[#24251C]">
                        {rec.student_name || rec.usn}
                      </td>
                      <td className="py-3 px-4 text-xs text-[#77735F]">
                        {rec.room_id && rec.room_id !== "UNALLOCATED" ? (
                          rec.room_id
                        ) : (
                          <span className="text-[#A9AE8C] font-mono">—</span>
                        )}
                      </td>
                      <td className="py-3 px-4">
                        {canMarkAttendance ? (
                          /* Clean 3-Option Segmented Control (Present | Absent | Pending) with implicit Unreviewed */
                          <div className="inline-flex rounded-lg border border-[#E4DDCA] p-0.5 bg-white space-x-0.5 shadow-2xs">
                            <button
                              type="button"
                              onClick={() =>
                                handleStatusChange(
                                  rec.usn,
                                  rec.status === "PRESENT" ? "UNREVIEWED" : "PRESENT"
                                )
                              }
                              title={rec.status === "PRESENT" ? "Click to clear (Unreviewed)" : "Mark Present"}
                              className={`px-2.5 py-1 rounded-md text-[11px] font-bold transition-all cursor-pointer ${
                                rec.status === "PRESENT"
                                  ? "bg-emerald-600 text-white shadow-2xs"
                                  : "text-[#77735F] hover:bg-emerald-50 hover:text-emerald-700"
                              }`}
                            >
                              Present
                            </button>
                            <button
                              type="button"
                              onClick={() =>
                                handleStatusChange(
                                  rec.usn,
                                  rec.status === "ABSENT" ? "UNREVIEWED" : "ABSENT"
                                )
                              }
                              title={rec.status === "ABSENT" ? "Click to clear (Unreviewed)" : "Mark Absent"}
                              className={`px-2.5 py-1 rounded-md text-[11px] font-bold transition-all cursor-pointer ${
                                rec.status === "ABSENT"
                                  ? "bg-rose-600 text-white shadow-2xs"
                                  : "text-[#77735F] hover:bg-rose-50 hover:text-rose-700"
                              }`}
                            >
                              Absent
                            </button>
                            <button
                              type="button"
                              onClick={() =>
                                handleStatusChange(
                                  rec.usn,
                                  rec.status === "PENDING" ? "UNREVIEWED" : "PENDING"
                                )
                              }
                              title={rec.status === "PENDING" ? "Click to clear (Unreviewed)" : "Mark Pending"}
                              className={`px-2.5 py-1 rounded-md text-[11px] font-bold transition-all cursor-pointer ${
                                rec.status === "PENDING"
                                  ? "bg-amber-500 text-white shadow-2xs"
                                  : "text-[#77735F] hover:bg-amber-50 hover:text-amber-800"
                              }`}
                            >
                              Pending
                            </button>
                          </div>
                        ) : (
                          <span
                            className={`inline-block px-2.5 py-0.5 rounded-lg text-xs font-bold border ${
                              rec.status === "PRESENT"
                                ? "bg-emerald-100 text-emerald-800 border-emerald-300"
                                : rec.status === "ABSENT"
                                ? "bg-rose-100 text-rose-800 border-rose-300"
                                : rec.status === "PENDING"
                                ? "bg-amber-100 text-amber-800 border-amber-300"
                                : "bg-stone-100 text-stone-700 border-stone-300"
                            }`}
                          >
                            {rec.status}
                          </span>
                        )}
                      </td>
                      <td className="py-3 pr-4 sm:pr-6 text-right">
                        {canMarkAttendance ? (
                          <button
                            type="button"
                            onClick={() => {
                              setReconcileTarget(rec);
                              setReconcileStatus(rec.status);
                            }}
                            className="inline-flex items-center space-x-1 px-2.5 py-1 rounded-lg text-xs font-semibold text-[#77735F] group-hover:text-[#6C5119] border border-transparent group-hover:border-[#E4DDCA] group-hover:bg-[#EDE8D8]/50 transition-all cursor-pointer"
                          >
                            <span>Reconcile</span>
                            <span>→</span>
                          </button>
                        ) : (
                          <span className="text-[11px] text-[#77735F] font-mono">Read-Only</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Dual-Source Reconciliation Modal */}
      {reconcileTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-xs">
          <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-6 max-w-md w-full shadow-xl space-y-4 animate-fadeIn">
            <div className="flex items-center justify-between pb-2 border-b border-[#E4DDCA]">
              <h3 className="text-base font-bold text-[#24251C]">Reconcile Student Attendance</h3>
              <button
                onClick={() => setReconcileTarget(null)}
                className="text-[#77735F] hover:text-[#24251C] text-sm font-bold"
              >
                ✕
              </button>
            </div>

            <div className="text-xs space-y-2 p-3 rounded-xl bg-[#EDE8D8]/40 border border-[#E4DDCA]">
              <p>
                <span className="font-semibold text-[#77735F]">Target USN: </span>
                <span className="font-bold text-[#6C5119]">{reconcileTarget.usn}</span>
              </p>
              <p>
                <span className="font-semibold text-[#77735F]">Current Status: </span>
                <span className="font-bold text-[#24251C]">{reconcileTarget.status}</span>
              </p>
              <p>
                <span className="font-semibold text-[#77735F]">Confidence Score: </span>
                <span>{reconcileTarget.confidence !== undefined ? `${(reconcileTarget.confidence * 100).toFixed(0)}%` : "100%"}</span>
              </p>
            </div>

            <form onSubmit={handleReconcileSubmit} className="space-y-4 text-xs sm:text-sm">
              <div>
                <label className="block font-semibold text-[#24251C] mb-1">
                  Resolved Target Status *
                </label>
                <select
                  value={reconcileStatus}
                  onChange={(e) => setReconcileStatus(e.target.value as AttendanceStatus)}
                  className="w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-[#24251C] font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
                >
                  <option value="PRESENT">PRESENT (Confirmed Attended)</option>
                  <option value="ABSENT">ABSENT (Confirmed Absent)</option>
                  <option value="PENDING">PENDING (Under Manual Review)</option>
                  <option value="UNREVIEWED">UNREVIEWED (Requires Discrepancy Check)</option>
                </select>
              </div>

              <div className="pt-2 flex justify-end space-x-2">
                <button
                  type="button"
                  onClick={() => setReconcileTarget(null)}
                  className="px-4 py-2 rounded-xl bg-[#EDE8D8] text-[#24251C] hover:bg-[#E4DDCA] font-semibold text-xs transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isReconciling}
                  className="px-4 py-2 rounded-xl bg-[#6C5119] hover:bg-[#594214] text-white font-bold text-xs shadow-2xs transition-colors disabled:opacity-50 cursor-pointer"
                >
                  {isReconciling ? "Reconciling..." : "Confirm Reconciliation"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
