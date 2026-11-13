"use client";

import React, { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  createSession,
  fetchInitializationState,
  fetchSessionAllocations,
  fetchSessions,
  initializeSessions,
  type InitializationState,
  type SessionAllocation,
  type SessionItem,
} from "@/services/api/sessions";
import { fetchMySubjects } from "@/services/api/faculty";
import { invalidate, mutateCache } from "@/services/api/cache";
import { useResource } from "@/hooks/useResource";
import { useAuth } from "@/hooks/useAuth";
import { formatIsoDate, todayIso } from "@/lib/schedule";

// Shared cache keys (module scope so mutation handlers and other views can
// invalidate/mutate the exact same entries without duplicating key logic).
export const SESSIONS_LIST_KEY = "/api/v1/sessions?limit=100";
const SESSIONS_ALLOCATIONS_KEY = "/api/v1/sessions/allocations";
const INITIALIZATION_KEY = (date: string) => `/api/v1/sessions/initialization/today?date=${date}`;
const MY_SUBJECTS_KEY = "/api/v1/me/subjects";

interface SessionsListResponse {
  items?: SessionItem[];
  total?: number;
}

export function SessionsView() {
  const navigate = useNavigate();
  const { session, isAdmin, isFaculty, isViewer, canScheduleSessions } = useAuth();
  const today = todayIso();

  // Cached reads: instant render on tab re-entry, background revalidation
  // when older than the stale time.
  const sessionsRes = useResource<SessionsListResponse>(
    SESSIONS_LIST_KEY,
    () => fetchSessions({ limit: 100 })
  );
  const allocationsRes = useResource<{ items?: SessionAllocation[]; total?: number }>(
    SESSIONS_ALLOCATIONS_KEY,
    () =>
      fetchSessionAllocations().catch(() => ({ items: [] as SessionAllocation[], total: 0 }))
  );
  const initializationRes = useResource<InitializationState>(
    INITIALIZATION_KEY(today),
    () => fetchInitializationState(today)
  );
  const subjectsRes = useResource<{ subject_codes?: string[] }>(
    isFaculty && !isAdmin ? MY_SUBJECTS_KEY : null,
    () => fetchMySubjects()
  );

  const sessions = useMemo(() => sessionsRes.data?.items ?? [], [sessionsRes.data]);
  const allocations = useMemo(
    () => allocationsRes.data?.items ?? [],
    [allocationsRes.data]
  );
  const isLoading = sessionsRes.isLoading;
  const error = sessionsRes.error
    ? sessionsRes.error instanceof Error
      ? sessionsRes.error.message
      : "Unable to load academic sessions."
    : null;

  const initialization = initializationRes.data ?? null;
  const initializationError = initializationRes.error
    ? initializationRes.error instanceof Error
      ? initializationRes.error.message
      : "The initialization state could not be read."
    : null;
  const [isInitializing, setIsInitializing] = useState(false);

  // Assigned subjects for faculty (authoritative from backend)
  const assignedSubjects = useMemo(
    () => subjectsRes.data?.subject_codes ?? [],
    [subjectsRes.data]
  );
  const isLoadingSubjects = subjectsRes.isLoading;

  const [subjectCodeChoice, setSubjectCodeChoice] = useState<string | null>(null);
  const subjectCodeFromSession = (!isAdmin && isFaculty && session.subjectCodes?.[0]) || "";
  const subjectCode = subjectCodeChoice ?? (assignedSubjects.length === 1 ? assignedSubjects[0] : subjectCodeFromSession);
  const setSubjectCode = setSubjectCodeChoice;

  // Search & filter
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedSubject, setSelectedSubject] = useState("ALL");

  // Create modal
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [sessionId, setSessionId] = useState("");
  const [sessionDate, setSessionDate] = useState(today);
  const [subject, setSubject] = useState("");

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Detail modal
  const [viewSession, setViewSession] = useState<SessionItem | null>(null);

  useEffect(() => {
    // Preselect the subject code once the authoritative list arrives.
    const codes = assignedSubjects;
    if (!isAdmin && isFaculty && codes.length > 0) {
      setSubjectCode((prev) => (prev ? prev : codes.length > 0 ? codes[0] : ""));
    }
  }, [isAdmin, isFaculty, assignedSubjects]);

  const allocationsBySession = useMemo(() => {
    const map = new Map<string, SessionAllocation[]>();
    for (const allocation of allocations) {
      const list = map.get(allocation.session_id) || [];
      list.push(allocation);
      map.set(allocation.session_id, list);
    }
    for (const list of map.values()) {
      list.sort((a, b) => (a.start_time || "").localeCompare(b.start_time || ""));
    }
    return map;
  }, [allocations]);

  const filteredSessions = useMemo(
    () =>
      sessions.filter((s) => {
        const matchesSearch =
          s.session_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
          (s.subject ? s.subject.toLowerCase().includes(searchQuery.toLowerCase()) : false) ||
          (s.subject_code ? s.subject_code.toLowerCase().includes(searchQuery.toLowerCase()) : false);
        const matchesSubject =
          selectedSubject === "ALL" ||
          (s.subject_code || s.subject || "").toUpperCase() === selectedSubject.toUpperCase();
        return matchesSearch && matchesSubject;
      }),
    [sessions, searchQuery, selectedSubject]
  );

  const subjectOptions = useMemo(() => {
    const set = new Set<string>();
    sessions.forEach((s) => {
      const value = s.subject_code || s.subject;
      if (value) set.add(value);
    });
    return Array.from(set).sort();
  }, [sessions]);

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canScheduleSessions || isViewer) {
      setFormError("You do not have permission to schedule academic sessions.");
      return;
    }
    if (!isAdmin && isFaculty && assignedSubjects.length === 0) {
      setFormError("Cannot schedule a session: no subjects are assigned to your account.");
      return;
    }
    if (!isAdmin && isFaculty && !subjectCode.trim()) {
      setFormError("Please select an assigned subject code.");
      return;
    }
    if (!sessionId.trim() || !subject.trim() || !sessionDate.trim()) {
      setFormError("Please fill out all required fields.");
      return;
    }

    setIsSubmitting(true);
    setFormError(null);
    try {
      const created = await createSession({
        session_id: sessionId.trim().toUpperCase(),
        date: sessionDate.trim(),
        subject: subject.trim(),
        subject_code: subjectCode.trim().toUpperCase() || undefined,
      });
      // Optimistic cache update instead of a full refetch: the new session is
      // prepended to the shared cached list and dependent keys are refreshed
      // in the background by whoever has them mounted.
      mutateCache<SessionsListResponse>(SESSIONS_LIST_KEY, (prev) => ({
        ...(prev ?? { items: [], total: 0 }),
        items: [created, ...(prev?.items ?? [])],
        total: (prev?.total ?? 0) + 1,
      }));
      invalidate(["dashboard", "calendar-month", "analytics"]);
      setIsCreateOpen(false);
      setSessionId("");
      setSubject("");
      setSubjectCode(assignedSubjects.length === 1 ? assignedSubjects[0] : "");
      window.dispatchEvent(new CustomEvent("rollcall:sessions-changed"));
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "Failed to schedule the session.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleInitialize = async () => {
    setIsInitializing(true);
    setInitializationError(null);
    try {
      await initializeSessions(today);
      // Only the affected keys: sessions/allocations/initialisation state here,
      // plus the dashboards/calendars that derive from them (refetched by the
      // hooks that currently have them mounted).
      invalidate([
        SESSIONS_LIST_KEY,
        SESSIONS_ALLOCATIONS_KEY,
        INITIALIZATION_KEY(today),
        "dashboard",
        "calendar-month",
        "analytics",
      ]);
      window.dispatchEvent(new CustomEvent("rollcall:sessions-changed"));
    } catch (err: unknown) {
      setInitializationError(
        err instanceof Error ? err.message : "The sessions could not be initialised."
      );
    } finally {
      setIsInitializing(false);
    }
  };

  const statusTone = (status?: string) => {
    switch (status) {
      case "INITIALIZED":
        return "bg-emerald-50 text-emerald-800 border-emerald-200";
      case "PENDING":
        return "bg-amber-50 text-amber-800 border-amber-200";
      case "FAILED":
        return "bg-rose-50 text-rose-800 border-rose-200";
      default:
        return "bg-[#EDE8D8]/50 text-[#77735F] border-[#E4DDCA]";
    }
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-2">
        <div>
          <div className="flex items-center space-x-2.5 flex-wrap gap-y-1">
            <h1 className="text-2xl sm:text-3xl font-extrabold text-[#24251C] tracking-tight">
              Academic Sessions
            </h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-[#EDE8D8] text-[#6C5119] border border-[#E4DDCA]">
              {isLoading ? "..." : `${sessions.length} recorded`}
            </span>
            {isViewer && (
              <span className="px-3 py-1 rounded-xl bg-slate-100 text-slate-700 border border-slate-300 text-xs font-bold flex items-center space-x-1.5 shadow-2xs">
                Read-Only Viewer
              </span>
            )}
          </div>
          <p className="text-xs sm:text-sm text-[#77735F] mt-1">
            Session records, class slots and the daily automatic initialisation state.
          </p>
        </div>

        {canScheduleSessions && !isViewer ? (
          <button
            type="button"
            onClick={() => setIsCreateOpen(true)}
            disabled={!isAdmin && isFaculty && !isLoadingSubjects && assignedSubjects.length === 0}
            className="inline-flex items-center space-x-2 px-4 py-2.5 rounded-xl text-xs sm:text-sm font-bold bg-[#6C5119] hover:bg-[#594214] text-white shadow-2xs transition-colors cursor-pointer self-start sm:self-auto disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Schedule Session
          </button>
        ) : (
          <span className="px-3.5 py-1.5 rounded-xl bg-[#EDE8D8] text-[#77735F] text-xs font-semibold border border-[#E4DDCA] flex items-center space-x-1.5 self-start sm:self-auto">
            Read-Only Session Registry
          </span>
        )}
      </div>

      {/* Initialisation panel */}
      <section className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-5 shadow-2xs space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h2 className="text-base font-bold text-[#24251C]">Today's academic sessions</h2>
            <p className="text-xs text-[#77735F] mt-0.5">
              {initialization?.message ||
                "Reading the initialisation state from the RollCall AI backend…"}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span
              className={`px-2.5 py-1 rounded-lg text-[10px] font-black uppercase tracking-wider border ${
                statusTone(initialization?.status)
              }`}
            >
              {initialization?.status?.replace("_", " ") ?? "Loading"}
            </span>
            <button
              type="button"
              onClick={() => void handleInitialize()}
              disabled={isInitializing}
              className="px-3.5 py-2 rounded-xl bg-[#3F451F] text-[#EDE8D8] text-xs font-bold hover:bg-[#343919] transition-colors disabled:opacity-50 cursor-pointer"
              title="Ask the backend to prepare today's sessions from the timetable (idempotent)"
            >
              {isInitializing ? "Initialising…" : "Initialise today"}
            </button>
          </div>
        </div>

        {initialization && (
          <div className="grid grid-cols-3 gap-3 text-center">
            <div className="p-2.5 rounded-xl bg-white border border-[#E4DDCA]">
              <p className="text-[10px] font-black uppercase tracking-wider text-[#77735F]">
                Scheduled
              </p>
              <p className="text-lg font-black text-[#24251C]">{initialization.scheduled_slots}</p>
            </div>
            <div className="p-2.5 rounded-xl bg-white border border-[#E4DDCA]">
              <p className="text-[10px] font-black uppercase tracking-wider text-[#77735F]">
                Initialised
              </p>
              <p className="text-lg font-black text-emerald-700">
                {initialization.initialized_sessions}
              </p>
            </div>
            <div className="p-2.5 rounded-xl bg-white border border-[#E4DDCA]">
              <p className="text-[10px] font-black uppercase tracking-wider text-[#77735F]">
                Pending
              </p>
              <p className="text-lg font-black text-amber-700">{initialization.pending_sessions}</p>
            </div>
          </div>
        )}

        {initializationError && (
          <p className="text-xs font-semibold text-rose-700">{initializationError}</p>
        )}

        <p className="text-[11px] text-[#77735F]">
          Session preparation runs on the server (idempotent, working days only, inside the
          09:00 - 17:00 academic day). The button above is a manual recovery action - it never
          creates duplicates.
        </p>
      </section>

      {!isAdmin && isFaculty && !isLoadingSubjects && assignedSubjects.length === 0 && (
        <div className="bg-[#FFF8E1] border border-[#FFE082] rounded-xl p-3.5 text-xs text-[#6C5119]">
          You have no assigned subjects. Session creation is disabled until an administrator
          assigns a subject code to your faculty account.
        </div>
      )}

      {error && (
        <div className="bg-[#FFF8E1] border border-[#FFE082] rounded-xl p-4 flex items-center justify-between text-xs text-[#6C5119]">
          <span>{error}</span>
          <button
            type="button"
            onClick={sessionsRes.refresh}
            className="font-bold underline hover:text-[#24251C] transition-colors ml-4 cursor-pointer"
          >
            Retry
          </button>
        </div>
      )}

      {/* Filters */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-2xs flex flex-col sm:flex-row items-center justify-between gap-3">
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search by session ID, course or code..."
          className="w-full sm:w-80 px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs sm:text-sm text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
        />

        <div className="flex items-center space-x-2.5 w-full sm:w-auto">
          <label className="text-xs font-semibold text-[#77735F] whitespace-nowrap">Subject:</label>
          <select
            value={selectedSubject}
            onChange={(e) => setSelectedSubject(e.target.value)}
            className="px-3 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs font-medium text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119] cursor-pointer"
          >
            <option value="ALL">All Subjects</option>
            {subjectOptions.map((sub) => (
              <option key={sub} value={sub}>
                {sub}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Sessions */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-6">
        {isLoading && (
          <div className="col-span-full py-16 text-center text-[#77735F]">
            <div className="w-6 h-6 border-2 border-[#6C5119] border-t-transparent rounded-full animate-spin mx-auto mb-2" />
            <span>Loading session records…</span>
          </div>
        )}

        {!isLoading && filteredSessions.length === 0 && (
          <div className="col-span-full py-16 text-center bg-[#FBF8F0] border border-dashed border-[#E4DDCA] rounded-2xl">
            <p className="font-bold text-[#24251C]">No academic sessions found</p>
            <p className="text-xs text-[#77735F] mt-1">
              Schedule a session or change your filter parameters.
            </p>
          </div>
        )}

        {!isLoading &&
          filteredSessions.map((sess) => {
            const code = sess.subject_code || sess.session_id;
            const slot = allocationsBySession.get(sess.session_id) ?? [];
            const first = slot[0];
            const isToday = sess.date === today;

            return (
              <div
                key={sess.session_id}
                className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-5 shadow-2xs hover:border-[#6C5119]/40 transition-all flex flex-col justify-between space-y-4"
              >
                <div className="space-y-3">
                  <div className="flex items-start justify-between gap-2">
                    <span className="px-2.5 py-1 rounded-md text-xs font-black bg-[#EDE8D8] text-[#6C5119] border border-[#E4DDCA]">
                      {code}
                    </span>
                    <span className="text-xs font-semibold text-[#77735F]">
                      {formatIsoDate(sess.date)}
                    </span>
                  </div>

                  <div>
                    <h3
                      onClick={() =>
                        navigate(`/attendance?session=${encodeURIComponent(sess.session_id)}`)
                      }
                      className="font-extrabold text-base text-[#24251C] line-clamp-1 cursor-pointer hover:text-[#6C5119] transition-colors"
                      title="Open the attendance ledger"
                    >
                      {sess.subject}
                    </h3>
                    <div className="flex items-center space-x-2 text-xs text-[#77735F] mt-0.5 flex-wrap">
                      <span>
                        ID: <span className="font-mono text-[#24251C]">{sess.session_id}</span>
                      </span>
                      {sess.teacher_id && (
                        <>
                          <span>•</span>
                          <span>
                            Faculty:{" "}
                            <span className="font-semibold text-[#24251C]">{sess.teacher_id}</span>
                          </span>
                        </>
                      )}
                    </div>
                  </div>

                  {/* Real class slot information */}
                  <div className="pt-1 flex flex-wrap gap-1.5 text-[11px]">
                    {first ? (
                      <>
                        <span className="px-2 py-0.5 rounded-md bg-[#EDE8D8]/70 text-[#24251C] font-medium border border-[#E4DDCA]">
                          Room: {first.room_id}
                        </span>
                        {first.batch_id && (
                          <span className="px-2 py-0.5 rounded-md bg-[#EDE8D8]/70 text-[#24251C] font-medium border border-[#E4DDCA]">
                            Batch: {first.batch_id}
                          </span>
                        )}
                        <span className="px-2 py-0.5 rounded-md bg-[#EDE8D8]/70 text-[#77735F] font-medium border border-[#E4DDCA]">
                          Time: {first.start_time} - {first.end_time}
                        </span>
                      </>
                    ) : (
                      <span className="px-2 py-0.5 rounded-md bg-[#EDE8D8]/40 text-[#77735F] font-medium border border-dashed border-[#E4DDCA]">
                        No class slot allocated
                      </span>
                    )}
                    {isToday && (
                      <span className="px-2 py-0.5 rounded-md bg-[#3F451F] text-[#EDE8D8] font-bold">
                        Today
                      </span>
                    )}
                  </div>
                </div>

                <div className="pt-3 border-t border-[#E4DDCA]/60 flex items-center justify-between">
                  <button
                    type="button"
                    onClick={() => setViewSession(sess)}
                    className="text-xs font-bold text-[#77735F] hover:text-[#24251C] transition-colors cursor-pointer"
                  >
                    Session details
                  </button>

                  <Link
                    to={`/attendance?session=${encodeURIComponent(sess.session_id)}`}
                    className="inline-flex items-center space-x-1 px-3 py-1.5 rounded-xl text-xs font-bold bg-[#6C5119] hover:bg-[#594214] text-white shadow-2xs transition-colors"
                  >
                    <span>Attendance Ledger</span>
                    <span>→</span>
                  </Link>
                </div>
              </div>
            );
          })}
      </div>

      {/* Detail modal */}
      {viewSession && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-[2px]">
          <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-6 max-w-md w-full shadow-xl space-y-4">
            <div className="flex items-center justify-between pb-2 border-b border-[#E4DDCA]">
              <h3 className="text-base font-bold text-[#24251C]">Session details</h3>
              <button
                type="button"
                onClick={() => setViewSession(null)}
                aria-label="Close"
                className="text-[#77735F] hover:text-[#24251C] text-sm font-bold cursor-pointer"
              >
                ✕
              </button>
            </div>

            <div className="space-y-3 text-xs sm:text-sm">
              <div className="flex justify-between py-1.5 border-b border-[#E4DDCA]/50">
                <span className="text-[#77735F]">Session ID</span>
                <span className="font-mono font-bold text-[#6C5119]">{viewSession.session_id}</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-[#E4DDCA]/50">
                <span className="text-[#77735F]">Subject</span>
                <span className="font-semibold text-[#24251C]">{viewSession.subject}</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-[#E4DDCA]/50">
                <span className="text-[#77735F]">Subject code</span>
                <span className="font-bold text-[#24251C]">{viewSession.subject_code || "—"}</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-[#E4DDCA]/50">
                <span className="text-[#77735F]">Scheduled date</span>
                <span className="text-[#24251C]">{formatIsoDate(viewSession.date)}</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-[#E4DDCA]/50">
                <span className="text-[#77735F]">Assigned faculty</span>
                <span className="text-[#24251C]">{viewSession.teacher_id || "Unassigned"}</span>
              </div>
              <div className="flex justify-between py-1.5">
                <span className="text-[#77735F]">Class slots</span>
                <span className="text-[#24251C]">
                  {(allocationsBySession.get(viewSession.session_id) ?? []).length}
                </span>
              </div>
            </div>

            {(allocationsBySession.get(viewSession.session_id) ?? []).length > 0 && (
              <ul className="space-y-2">
                {(allocationsBySession.get(viewSession.session_id) ?? []).map((slot) => (
                  <li
                    key={slot.allocation_id}
                    className="p-3 rounded-xl bg-white border border-[#E4DDCA] text-xs space-y-1"
                  >
                    <p className="font-bold text-[#24251C]">
                      {slot.start_time} - {slot.end_time}
                    </p>
                    <p className="text-[#77735F]">
                      Room {slot.room_id}
                      {slot.batch_id ? ` · Batch ${slot.batch_id}` : ""}
                    </p>
                    <p className="text-[10px] font-black uppercase tracking-wider text-[#77735F]">
                      {slot.lifecycle_status || "SCHEDULED"}
                    </p>
                  </li>
                ))}
              </ul>
            )}

            <div className="pt-2 flex justify-end">
              <button
                type="button"
                onClick={() => setViewSession(null)}
                className="px-4 py-2 rounded-xl bg-[#EDE8D8] text-[#24251C] hover:bg-[#E4DDCA] font-bold text-xs transition-colors cursor-pointer"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Schedule modal */}
      {isCreateOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-[2px] overflow-y-auto">
          <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-6 max-w-md w-full shadow-xl space-y-4 my-8">
            <div className="flex items-center justify-between pb-2 border-b border-[#E4DDCA]">
              <h3 className="text-base font-bold text-[#24251C]">Schedule New Session</h3>
              <button
                type="button"
                onClick={() => setIsCreateOpen(false)}
                aria-label="Close"
                className="text-[#77735F] hover:text-[#24251C] text-sm font-bold cursor-pointer"
              >
                ✕
              </button>
            </div>

            {formError && (
              <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 text-xs">
                {formError}
              </div>
            )}

            <form onSubmit={handleCreateSubmit} className="space-y-4 text-xs sm:text-sm">
              <div>
                <label className="block font-semibold text-[#24251C] mb-1">
                  Session Identifier *
                </label>
                <input
                  type="text"
                  value={sessionId}
                  onChange={(e) => setSessionId(e.target.value)}
                  placeholder="e.g. SESS-2026-11-10-CS"
                  required
                  className="w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-[#24251C] uppercase focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
                />
              </div>

              <div>
                <label className="block font-semibold text-[#24251C] mb-1">
                  Subject / Course Title *
                </label>
                <input
                  type="text"
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  placeholder="e.g. Distributed Systems Architecture"
                  required
                  className="w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
                />
              </div>

              {!isAdmin && isFaculty ? (
                <div>
                  <label className="block font-semibold text-[#24251C] mb-1">
                    Assigned Subject Code *
                  </label>
                  {assignedSubjects.length === 0 ? (
                    <div className="p-3 rounded-xl bg-amber-50 border border-amber-300 text-amber-900 text-xs">
                      No subjects are assigned to your faculty account. You cannot create a
                      session.
                    </div>
                  ) : assignedSubjects.length === 1 ? (
                    <div className="px-3.5 py-2.5 rounded-xl bg-[#EDE8D8]/70 border border-[#E4DDCA] text-xs font-mono font-bold text-[#6C5119] flex items-center justify-between">
                      <span>{assignedSubjects[0]}</span>
                      <span className="text-[11px] font-sans font-normal text-[#77735F]">
                        Auto-selected
                      </span>
                    </div>
                  ) : (
                    <select
                      value={subjectCode}
                      onChange={(e) => setSubjectCode(e.target.value)}
                      required
                      className="w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-[#24251C] uppercase focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119] cursor-pointer"
                    >
                      <option value="">-- Select Assigned Subject --</option>
                      {assignedSubjects.map((code) => (
                        <option key={code} value={code}>
                          {code}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
              ) : (
                <div>
                  <label className="block font-semibold text-[#24251C] mb-1">Subject Code</label>
                  <input
                    type="text"
                    value={subjectCode}
                    onChange={(e) => setSubjectCode(e.target.value)}
                    placeholder="e.g. DIST-SYS"
                    className="w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-[#24251C] uppercase focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
                  />
                </div>
              )}

              <div>
                <label className="block font-semibold text-[#24251C] mb-1">
                  Scheduled Calendar Date *
                </label>
                <input
                  type="date"
                  value={sessionDate}
                  onChange={(e) => setSessionDate(e.target.value)}
                  required
                  className="w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
                />
                <p className="mt-1 text-[11px] text-[#77735F]">
                  Class times come from the timetable (09:00 - 17:00). A manually created
                  session has no time slot until the timetable allocates one.
                </p>
              </div>

              <div className="pt-2 flex justify-end space-x-2">
                <button
                  type="button"
                  onClick={() => setIsCreateOpen(false)}
                  className="px-4 py-2 rounded-xl bg-[#EDE8D8] text-[#24251C] hover:bg-[#E4DDCA] font-semibold text-xs transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-4 py-2 rounded-xl bg-[#6C5119] hover:bg-[#594214] text-white font-bold text-xs shadow-2xs transition-colors disabled:opacity-50 cursor-pointer"
                >
                  {isSubmitting ? "Creating…" : "Save Session"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
