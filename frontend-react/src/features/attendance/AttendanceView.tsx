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
import { fetchRooms, type Room } from "@/services/api/rooms";
import { useAuth } from "@/hooks/useAuth";
import {
  fetchSessionAttendance,
  updateSessionAttendance,
  reconcileAttendance,
  createAttendanceUnlockRequest,
  fetchAttendanceUnlockRequests,
  reviewAttendanceUnlockRequest,
  type AttendanceRecord,
  type AttendanceStatus,
  type AttendanceUnlockRequest,
} from "@/services/api/attendance";

export function AttendanceView() {
  const [searchParams] = useSearchParams();
  const querySession = searchParams.get("session") || searchParams.get("sessionId") || "";
  const { session, isAdmin, isFaculty, isViewer, canMarkAttendance } = useAuth();
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  // Real class slots (room / batch / time) of the sessions the caller may see.
  const [allocations, setAllocations] = useState<SessionAllocation[]>([]);
  const [availableRooms, setAvailableRooms] = useState<Room[]>([]);
  const [selectedRoomOverride, setSelectedRoomOverride] = useState<string>("");
  const [selectedSessionId, setSelectedSessionId] = useState<string>(querySession);
  const [attendanceRecords, setAttendanceRecords] = useState<AttendanceRecord[]>([]);
  const [isLoadingSessions, setIsLoadingSessions] = useState(true);
  const [isLoadingAttendance, setIsLoadingAttendance] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [statusMessage, setStatusMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // Reconciliation modal state
  const [reconcileTarget, setReconcileTarget] = useState<AttendanceRecord | null>(null);
  const [reconcileStatus, setReconcileStatus] = useState<AttendanceStatus>("PRESENT");
  const [isReconciling, setIsReconciling] = useState(false);

  // Attendance Unlock Request (>24h edit permission) state
  const [activeUnlockRequest, setActiveUnlockRequest] = useState<AttendanceUnlockRequest | null>(null);
  const [pendingAdminRequests, setPendingAdminRequests] = useState<AttendanceUnlockRequest[]>([]);
  const [isUnlockModalOpen, setIsUnlockModalOpen] = useState(false);
  const [unlockReason, setUnlockReason] = useState("");
  const [unlockTargetUsn, setUnlockTargetUsn] = useState("");
  const [unlockChangeDesc, setUnlockChangeDesc] = useState("Mark Present due to medical / OD leave");
  const [isSubmittingUnlock, setIsSubmittingUnlock] = useState(false);

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

  // Load available sessions on mount
  useEffect(() => {
    let isMounted = true;
    Promise.resolve().then(() => {
      if (!isMounted) return;
      Promise.all([
        fetchSessions({ limit: 50 }),
        fetchSessionAllocations().catch(() => ({ items: [] as SessionAllocation[], total: 0 })),
        fetchRooms({ limit: 100 }).catch(() => ({ items: [] as Room[], total: 0, limit: 100, offset: 0 })),
      ])
        .then(([res, allocationsRes, roomsRes]) => {
          if (!isMounted) return;
          const allItems = res.items || [];
          setSessions(allItems);
          setAllocations(allocationsRes.items || []);
          setAvailableRooms(roomsRes.items || []);

          if (querySession) {
            setSelectedSessionId(querySession);
          } else {
            setSelectedSessionId((prev) => prev || (allItems.length > 0 ? allItems[0].session_id : ""));
          }
        })
        .catch((err: unknown) => {
          if (!isMounted) return;
          setStatusMessage({
            type: "error",
            text: formatApiError(err),
          });
        })
        .finally(() => {
          if (isMounted) setIsLoadingSessions(false);
        });
    });
    return () => {
      isMounted = false;
    };
  }, [querySession]);

  // Load attendance whenever selected session changes
  const loadAttendance = useCallback(async (sessionId: string, clearMessage = true) => {
    if (!sessionId) return;
    setIsLoadingAttendance(true);
    // Keep the save confirmation visible: a silent refresh after a successful
    // save used to wipe the "Saved" banner before the teacher could read it.
    if (clearMessage) setStatusMessage(null);
    try {
      const records = await fetchSessionAttendance(sessionId);
      setAttendanceRecords(records || []);
    } catch (err: unknown) {
      setStatusMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Failed to load session roster.",
      });
    } finally {
      setIsLoadingAttendance(false);
    }
  }, []);

  useEffect(() => {
    if (!selectedSessionId) return;
    setSelectedRoomOverride("");
    let isMounted = true;
    Promise.resolve().then(() => {
      if (isMounted) void loadAttendance(selectedSessionId);
    });
    return () => {
      isMounted = false;
    };
  }, [selectedSessionId, loadAttendance]);

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
  const effectiveRoom = selectedRoomOverride || sessionRoom || "UNALLOCATED";

  const isSessionLocked = useMemo(() => {
    if (isAdmin) return false;
    if (!activeSession) return false;
    if (activeSession.created_at) {
      const ageHours = (Date.now() - new Date(activeSession.created_at).getTime()) / (1000 * 60 * 60);
      return ageHours > 24;
    }
    if (activeSession.date) {
      const sessionDate = new Date(`${activeSession.date}T23:59:59Z`);
      const ageHours = (Date.now() - sessionDate.getTime()) / (1000 * 60 * 60);
      return ageHours > 24;
    }
    return false;
  }, [activeSession, isAdmin]);

  const isUnlockedByAdmin = useMemo(() => {
    if (!activeUnlockRequest) return false;
    if (activeUnlockRequest.status !== "APPROVED") return false;
    if (!activeUnlockRequest.expires_at) return true;
    return new Date(activeUnlockRequest.expires_at).getTime() > Date.now();
  }, [activeUnlockRequest]);

  // Load unlock request for current session
  const refreshUnlockRequest = useCallback(async () => {
    if (!selectedSessionId) {
      setActiveUnlockRequest(null);
      return;
    }
    try {
      const reqs = await fetchAttendanceUnlockRequests({ session_id: selectedSessionId });
      if (reqs && reqs.length > 0) {
        setActiveUnlockRequest(reqs[0]);
      } else {
        setActiveUnlockRequest(null);
      }
    } catch {
      setActiveUnlockRequest(null);
    }
  }, [selectedSessionId]);

  // Load all pending unlock requests for administrator
  const loadPendingAdminRequests = useCallback(async () => {
    if (!isAdmin) {
      setPendingAdminRequests([]);
      return;
    }
    try {
      const pending = await fetchAttendanceUnlockRequests({ status: "PENDING" });
      setPendingAdminRequests(pending || []);
    } catch {
      setPendingAdminRequests([]);
    }
  }, [isAdmin]);

  useEffect(() => {
    void refreshUnlockRequest();
    void loadPendingAdminRequests();

    const handleSync = () => {
      void refreshUnlockRequest();
      void loadPendingAdminRequests();
    };
    window.addEventListener("rollcall-unlock-request-updated", handleSync);
    return () => {
      window.removeEventListener("rollcall-unlock-request-updated", handleSync);
    };
  }, [refreshUnlockRequest, loadPendingAdminRequests]);

  const handleRequestUnlock = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedSessionId || !unlockReason.trim()) return;
    setIsSubmittingUnlock(true);
    try {
      const req = await createAttendanceUnlockRequest({
        session_id: selectedSessionId,
        reason: unlockReason.trim(),
        target_usns: unlockTargetUsn.trim() ? [unlockTargetUsn.trim().toUpperCase()] : undefined,
        requested_change: unlockChangeDesc.trim() || undefined,
      });
      setActiveUnlockRequest(req);
      setIsUnlockModalOpen(false);
      setUnlockReason("");
      setUnlockTargetUsn("");
      setStatusMessage({
        type: "success",
        text: "Permission request submitted to administrator successfully.",
      });
      window.dispatchEvent(new CustomEvent("rollcall-unlock-request-updated"));
    } catch (err: unknown) {
      setStatusMessage({
        type: "error",
        text: formatApiError(err),
      });
    } finally {
      setIsSubmittingUnlock(false);
    }
  };

  const handleReviewRequest = async (requestId: string, decision: "APPROVED" | "REJECTED") => {
    try {
      const updated = await reviewAttendanceUnlockRequest(requestId, {
        decision,
        unlock_hours: 24,
      });
      setActiveUnlockRequest(updated);
      setStatusMessage({
        type: "success",
        text: decision === "APPROVED" ? "Session unlocked for teacher edits (24h)." : "Unlock request rejected.",
      });
      window.dispatchEvent(new CustomEvent("rollcall-unlock-request-updated"));
      window.dispatchEvent(new CustomEvent("rollcall-attendance-updated"));
      void loadPendingAdminRequests();
    } catch (err: unknown) {
      setStatusMessage({
        type: "error",
        text: formatApiError(err),
      });
    }
  };

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
    if (isSessionLocked && !isUnlockedByAdmin) {
      setStatusMessage({
        type: "error",
        text: "Session is locked (>24h old). Please request permission from the administrator to make changes.",
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
    if (isSessionLocked && !isUnlockedByAdmin) {
      setStatusMessage({
        type: "error",
        text: "Session is locked (>24h old). Request permission from an admin to initialize or edit the roster.",
      });
      return;
    }
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
        room_id: effectiveRoom,
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
    if (isSessionLocked && !isUnlockedByAdmin) {
      setStatusMessage({
        type: "error",
        text: "Session is locked (>24h old). Request permission from an admin to edit marks.",
      });
      return;
    }
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
    if (isSessionLocked && !isUnlockedByAdmin) {
      setStatusMessage({
        type: "error",
        text: "Session is locked (>24h old). Submit an unlock request to the administrator to save changes.",
      });
      return;
    }
    if (attendanceRecords.length === 0) {
      setStatusMessage({
        type: "error",
        text: "No attendance records to save. Please load or add students to the roster first.",
      });
      return;
    }
    setIsSaving(true);
    setStatusMessage(null);

    try {
      const payload = attendanceRecords.map((r) => ({
        usn: r.usn,
        room_id: (r.room_id && r.room_id !== "UNALLOCATED") ? r.room_id : effectiveRoom,
        status: r.status,
      }));
      const res = await updateSessionAttendance(selectedSessionId, payload);
      setStatusMessage({
        type: "success",
        text: res.message || `Successfully synchronized ${payload.length} attendance marks for session '${selectedSessionId}'.`,
      });
      // Refresh roster directly from backend to ensure authoritative display
      await loadAttendance(selectedSessionId, false);
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
      setAttendanceRecords((prev) =>
        prev.map((r) =>
          r.usn === reconcileTarget.usn ? { ...r, status: reconcileStatus } : r
        )
      );
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
              disabled={attendanceRecords.length === 0 || isSaving || isLoadingAttendance}
              className="inline-flex items-center space-x-2 px-4 py-2 rounded-xl text-xs sm:text-sm font-bold bg-[#6C5119] hover:bg-[#594214] text-white shadow-2xs transition-colors disabled:opacity-50 cursor-pointer"
            >
              {isSaving ? (
                <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : (
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.2} d="M5 13l4 4L19 7" />
                </svg>
              )}
              <span>{isSaving ? "Saving..." : "Save Changes"}</span>
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

      {/* Session Selection & Allocation Metadata Card */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-5 shadow-2xs space-y-4">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          {/* Session Selector */}
          <div className="w-full lg:w-96">
            <label className="block text-xs font-bold text-[#77735F] uppercase tracking-wider mb-1.5">
              Select Attendance Session
            </label>
            <select
              value={selectedSessionId}
              onChange={(e) => setSelectedSessionId(e.target.value)}
              disabled={isLoadingSessions}
              className="w-full px-3.5 py-2.5 rounded-xl bg-white border border-[#E4DDCA] text-xs sm:text-sm font-semibold text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119] cursor-pointer"
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

          {/* Allocation Chips */}
          {activeSession && (
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="px-3 py-1.5 rounded-xl bg-[#EDE8D8] text-[#24251C] font-semibold border border-[#E4DDCA]">
                Subject: {activeSession.subject}
              </span>
              <span className="px-3 py-1.5 rounded-xl bg-[#EDE8D8] text-[#24251C] font-semibold border border-[#E4DDCA]">
                Date: {activeSession.date}
              </span>
              {sessionRooms.length > 0 ? (
                <span className="px-3 py-1.5 rounded-xl bg-[#EDE8D8] text-[#77735F] font-medium border border-[#E4DDCA]">
                  Room: {sessionRooms.join(", ")}
                </span>
              ) : (
                <div className="inline-flex items-center space-x-1.5 px-3 py-1 rounded-xl bg-[#EDE8D8] text-[#24251C] text-xs font-semibold border border-[#E4DDCA]">
                  <span className="text-[#77735F] font-medium">Room:</span>
                  <select
                    value={selectedRoomOverride || "UNALLOCATED"}
                    onChange={(e) => {
                      const newRoom = e.target.value;
                      setSelectedRoomOverride(newRoom);
                      setAttendanceRecords((prev) =>
                        prev.map((rec) => ({ ...rec, room_id: newRoom }))
                      );
                    }}
                    className="bg-transparent font-bold text-[#24251C] focus:outline-none cursor-pointer py-0.5"
                  >
                    <option value="UNALLOCATED">Not allocated / General</option>
                    {availableRooms
                      .filter((r) => r.room_id !== "UNALLOCATED")
                      .map((r) => (
                        <option key={r.room_id} value={r.room_id}>
                          {r.room_id} ({r.name})
                        </option>
                      ))}
                  </select>
                </div>
              )}
              <span className="px-3 py-1.5 rounded-xl bg-[#EDE8D8] text-[#77735F] font-medium border border-[#E4DDCA]">
                Time:{" "}
                {sessionSlot
                  ? `${sessionSlot.start_time} - ${sessionSlot.end_time}`
                  : "Not scheduled"}
                {sessionBatches.length > 0 ? ` (Batch ${sessionBatches.join(", ")})` : ""}
              </span>
            </div>
          )}
        </div>

        {/* 4 Attendance State Quick Counters */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2">
          {/* PRESENT */}
          <div className="bg-[#E8F5E9] border border-[#C8E6C9] rounded-xl p-3 text-center">
            <span className="text-[11px] font-bold text-[#2E7D32] uppercase">Present</span>
            <p className="text-xl sm:text-2xl font-black text-[#1B5E20]">{counts.present}</p>
          </div>

          {/* ABSENT */}
          <div className="bg-[#FFEBEE] border border-[#FFCDD2] rounded-xl p-3 text-center">
            <span className="text-[11px] font-bold text-[#C62828] uppercase">Absent</span>
            <p className="text-xl sm:text-2xl font-black text-[#B71C1C]">{counts.absent}</p>
          </div>

          {/* PENDING */}
          <div className="bg-[#FFF8E1] border border-[#FFE082] rounded-xl p-3 text-center">
            <span className="text-[11px] font-bold text-[#F57F17] uppercase">Pending</span>
            <p className="text-xl sm:text-2xl font-black text-[#E65100]">{counts.pending}</p>
          </div>

          {/* UNREVIEWED */}
          <div className="bg-[#EDE8D8] border border-[#DCD5BE] rounded-xl p-3 text-center">
            <span className="text-[11px] font-bold text-[#72785E] uppercase">Unreviewed</span>
            <p className="text-xl sm:text-2xl font-black text-[#3F451F]">{counts.unreviewed}</p>
          </div>
        </div>

        {/* Admin Overview Banner of Pending Unlock Requests Across All Sessions */}
        {isAdmin && pendingAdminRequests.length > 0 && (
          <div className="p-3.5 rounded-xl bg-amber-50 border-2 border-amber-300 text-amber-950 flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-2.5">
              <span className="text-xl">🔔</span>
              <div>
                <h4 className="font-bold text-xs sm:text-sm">
                  {pendingAdminRequests.length} Teacher Edit Permission Request{pendingAdminRequests.length > 1 ? "s" : ""} Pending Review
                </h4>
                <p className="text-[11px] text-amber-900/80">
                  Select a session below to review justification and grant or deny 24-hour temporary edit access.
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              {pendingAdminRequests.map((req) => (
                <button
                  key={req.request_id}
                  type="button"
                  onClick={() => setSelectedSessionId(req.session_id)}
                  className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all cursor-pointer ${
                    selectedSessionId === req.session_id
                      ? "bg-amber-700 text-white shadow-xs"
                      : "bg-white border border-amber-300 text-amber-900 hover:bg-amber-100"
                  }`}
                >
                  Review {req.subject_code || "Session"} ({req.teacher_name || req.teacher_id}) →
                </button>
              ))}
            </div>
          </div>
        )}

        {/* 24-Hour Edit Lock & Permission Request Banner */}
        {(isSessionLocked || Boolean(activeUnlockRequest)) && (
          <div
            className={`p-4 rounded-xl border flex items-center justify-between gap-4 flex-wrap text-xs ${
              isUnlockedByAdmin
                ? "bg-emerald-50 border-emerald-300 text-emerald-950"
                : activeUnlockRequest?.status === "PENDING"
                ? "bg-amber-50 border-amber-300 text-amber-950"
                : activeUnlockRequest?.status === "REJECTED"
                ? "bg-stone-100 border-stone-300 text-stone-800"
                : "bg-rose-50 border-rose-300 text-rose-950"
            }`}
          >
            <div className="flex items-center gap-3">
              <span className="text-xl">
                {isUnlockedByAdmin
                  ? "🔓"
                  : activeUnlockRequest?.status === "PENDING"
                  ? "⏳"
                  : activeUnlockRequest?.status === "REJECTED"
                  ? "❌"
                  : "🔒"}
              </span>
              <div>
                <h4 className="font-bold text-xs sm:text-sm">
                  {isAdmin
                    ? activeUnlockRequest?.status === "PENDING"
                      ? `Teacher Edit Permission Request · ${activeUnlockRequest.teacher_name || activeUnlockRequest.teacher_id}`
                      : isUnlockedByAdmin
                      ? `Teacher Temporary Unlock Active (Expires ${
                          activeUnlockRequest?.expires_at
                            ? new Date(activeUnlockRequest.expires_at).toLocaleTimeString([], {
                                hour: "2-digit",
                                minute: "2-digit",
                              })
                            : "end of window"
                        })`
                      : activeUnlockRequest?.status === "REJECTED"
                      ? "Teacher Edit Request Declined"
                      : "Session Older Than 24h"
                    : isUnlockedByAdmin
                    ? `Admin Override Active (Unlocked until ${
                        activeUnlockRequest?.expires_at
                          ? new Date(activeUnlockRequest.expires_at).toLocaleTimeString([], {
                              hour: "2-digit",
                              minute: "2-digit",
                            })
                          : "end of window"
                      })`
                    : activeUnlockRequest?.status === "PENDING"
                    ? "Edit Permission Request Pending Admin Review"
                    : activeUnlockRequest?.status === "REJECTED"
                    ? "Edit Permission Declined by Admin"
                    : "Session Locked (>24 Hours Old)"}
                </h4>
                <p className="text-xs opacity-90 mt-0.5 max-w-xl">
                  {isAdmin
                    ? activeUnlockRequest?.status === "PENDING"
                      ? `Submitted on ${activeUnlockRequest.created_at.slice(0, 10)}: "${activeUnlockRequest.reason}"${
                          activeUnlockRequest.target_usns ? ` • Target: ${activeUnlockRequest.target_usns}` : ""
                        }${activeUnlockRequest.requested_change ? ` • Change: ${activeUnlockRequest.requested_change}` : ""}`
                      : isUnlockedByAdmin
                      ? "The teacher currently has active override authorization to edit attendance."
                      : "Administrative master view."
                    : isUnlockedByAdmin
                    ? "You have temporary authorization from the administrator to modify and save attendance records."
                    : activeUnlockRequest?.status === "PENDING"
                    ? `Submitted on ${activeUnlockRequest.created_at.slice(0, 10)}: "${activeUnlockRequest.reason}"`
                    : activeUnlockRequest?.status === "REJECTED"
                    ? `Administrator declined the request${activeUnlockRequest.admin_notes ? `: "${activeUnlockRequest.admin_notes}"` : "."}`
                    : "Teacher editing is restricted after 24 hours of class. Submit a permission request to the administrator to unlock changes."}
                </p>
              </div>
            </div>

            {!isAdmin && !isUnlockedByAdmin && activeUnlockRequest?.status !== "PENDING" && (
              <button
                type="button"
                onClick={() => setIsUnlockModalOpen(true)}
                className="px-4 py-2 rounded-xl bg-[#6C5119] hover:bg-[#594214] text-white font-bold text-xs shadow-xs transition-all cursor-pointer whitespace-nowrap"
              >
                📨 Request Permission from Admin
              </button>
            )}

            {isAdmin && activeUnlockRequest?.status === "PENDING" && (
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => handleReviewRequest(activeUnlockRequest.request_id, "APPROVED")}
                  className="px-3.5 py-1.5 rounded-xl bg-emerald-700 hover:bg-emerald-800 text-white font-bold text-xs shadow-xs transition-all cursor-pointer"
                >
                  ✅ Approve (24h)
                </button>
                <button
                  type="button"
                  onClick={() => handleReviewRequest(activeUnlockRequest.request_id, "REJECTED")}
                  className="px-3.5 py-1.5 rounded-xl bg-rose-700 hover:bg-rose-800 text-white font-bold text-xs shadow-xs transition-all cursor-pointer"
                >
                  ❌ Reject
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Filter and Search Bar */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-2xs flex flex-col sm:flex-row items-center justify-between gap-3">
        <div className="relative w-full sm:w-80">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Filter roster by USN or student name..."
            className="w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs sm:text-sm text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
          />
        </div>

        <div className="flex items-center space-x-2.5 w-full sm:w-auto">
          <span className="text-xs font-semibold text-[#77735F]">Status Filter:</span>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="px-3 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs font-medium text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119] cursor-pointer"
          >
            <option value="ALL">All States ({attendanceRecords.length})</option>
            <option value="PRESENT">Present ({counts.present})</option>
            <option value="ABSENT">Absent ({counts.absent})</option>
            <option value="PENDING">Pending ({counts.pending})</option>
            <option value="UNREVIEWED">Unreviewed ({counts.unreviewed})</option>
          </select>
        </div>
      </div>

      {/* Student Roster Table */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl shadow-2xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs sm:text-sm">
            <thead>
              <tr className="border-b border-[#E4DDCA] bg-[#EDE8D8]/40 text-[#77735F] font-semibold">
                <th className="py-3.5 pl-4 sm:pl-6">USN</th>
                <th className="py-3.5 px-4">Student Name</th>
                <th className="py-3.5 px-4">Room Allocation</th>
                <th className="py-3.5 px-4">Status & Quick Toggle</th>
                <th className="py-3.5 pr-4 sm:pr-6 text-right">Reconciliation</th>
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
                    <tr key={rec.usn} className="hover:bg-[#EDE8D8]/20 transition-colors">
                      <td className="py-3.5 pl-4 sm:pl-6 font-bold text-[#6C5119]">
                        {rec.usn}
                      </td>
                      <td className="py-3.5 px-4 font-semibold text-[#24251C]">
                        {rec.student_name || rec.usn}
                      </td>
                      <td className="py-3.5 px-4 text-xs font-medium">
                        {rec.room_id && rec.room_id !== "UNALLOCATED" ? (
                          <span className="font-mono font-bold text-[#6C5119]">{rec.room_id}</span>
                        ) : (
                          <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-stone-100 text-stone-600 border border-stone-200">
                            Not allocated
                          </span>
                        )}
                      </td>
                      <td className="py-3.5 px-4">
                        {canMarkAttendance ? (
                          /* 4 State Toggle Pills */
                          <div className="inline-flex rounded-lg border border-[#E4DDCA] p-0.5 bg-white space-x-0.5">
                            <button
                              type="button"
                              onClick={() => handleStatusChange(rec.usn, "PRESENT")}
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
                              onClick={() => handleStatusChange(rec.usn, "ABSENT")}
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
                              onClick={() => handleStatusChange(rec.usn, "PENDING")}
                              className={`px-2.5 py-1 rounded-md text-[11px] font-bold transition-all cursor-pointer ${
                                rec.status === "PENDING"
                                  ? "bg-amber-500 text-white shadow-2xs"
                                  : "text-[#77735F] hover:bg-amber-50 hover:text-amber-800"
                              }`}
                            >
                              Pending
                            </button>
                            <button
                              type="button"
                              onClick={() => handleStatusChange(rec.usn, "UNREVIEWED")}
                              className={`px-2.5 py-1 rounded-md text-[11px] font-bold transition-all cursor-pointer ${
                                rec.status === "UNREVIEWED"
                                  ? "bg-[#72785E] text-white shadow-2xs"
                                  : "text-[#77735F] hover:bg-[#EDE8D8]"
                              }`}
                            >
                              Unreviewed
                            </button>
                          </div>
                        ) : (
                          <span
                            className={`inline-block px-3 py-1 rounded-lg text-xs font-bold border ${
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
                      <td className="py-3.5 pr-4 sm:pr-6 text-right">
                        {canMarkAttendance ? (
                          <button
                            type="button"
                            onClick={() => {
                              setReconcileTarget(rec);
                              setReconcileStatus(rec.status);
                            }}
                            className="px-3 py-1 rounded-lg text-xs font-semibold bg-[#EDE8D8] text-[#24251C] hover:bg-[#E4DDCA] transition-colors cursor-pointer"
                          >
                            Audit / Reconcile
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

      {/* Attendance Unlock Request Modal (>24h Permission) */}
      {isUnlockModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-xs animate-in fade-in duration-150">
          <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl max-w-lg w-full p-6 shadow-xl space-y-4">
            <div className="flex items-center justify-between pb-2 border-b border-[#E4DDCA]">
              <div className="flex items-center gap-2">
                <span className="text-xl">📨</span>
                <h3 className="text-base font-bold text-[#24251C]">Request Attendance Edit Permission</h3>
              </div>
              <button
                type="button"
                onClick={() => setIsUnlockModalOpen(false)}
                className="text-[#77735F] hover:text-[#24251C] text-sm font-bold cursor-pointer"
              >
                ✕
              </button>
            </div>

            <p className="text-xs text-[#77735F]">
              Session <span className="font-mono font-bold text-[#24251C]">{selectedSessionId}</span> is older than 24 hours. Submit a formal change request to the administrator with the justification.
            </p>

            <form onSubmit={handleRequestUnlock} className="space-y-3.5 text-xs sm:text-sm">
              <div>
                <label className="block font-bold text-[#24251C] mb-1">
                  Reason for Modification *
                </label>
                <textarea
                  value={unlockReason}
                  onChange={(e) => setUnlockReason(e.target.value)}
                  placeholder="e.g. Medical certificate verified for absent student, late OD duty approval, or optical reconciliation discrepancy"
                  required
                  rows={3}
                  className="w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
                />
              </div>

              <div>
                <label className="block font-bold text-[#24251C] mb-1">
                  Affected Student USN (Optional)
                </label>
                <input
                  type="text"
                  value={unlockTargetUsn}
                  onChange={(e) => setUnlockTargetUsn(e.target.value)}
                  placeholder="e.g. 1DS24CY015"
                  className="w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-[#24251C] font-mono focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
                />
              </div>

              <div>
                <label className="block font-bold text-[#24251C] mb-1">
                  Requested Change / Action
                </label>
                <input
                  type="text"
                  value={unlockChangeDesc}
                  onChange={(e) => setUnlockChangeDesc(e.target.value)}
                  placeholder="e.g. Mark Present due to medical / OD leave"
                  className="w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
                />
              </div>

              <div className="pt-2 flex justify-end space-x-2">
                <button
                  type="button"
                  onClick={() => setIsUnlockModalOpen(false)}
                  className="px-4 py-2 rounded-xl bg-[#EDE8D8] text-[#24251C] hover:bg-[#E4DDCA] font-semibold text-xs transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingUnlock || !unlockReason.trim()}
                  className="px-4 py-2 rounded-xl bg-[#6C5119] hover:bg-[#594214] text-white font-bold text-xs shadow-2xs transition-colors disabled:opacity-50 cursor-pointer"
                >
                  {isSubmittingUnlock ? "Submitting..." : "Send Request to Admin"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
