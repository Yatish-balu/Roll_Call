"use client";

import React, { useEffect, useState, useCallback, useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { fetchSessions, createSession, type SessionItem } from "@/services/api/sessions";
import { fetchMySubjects } from "@/services/api/faculty";
import { useAuth } from "@/hooks/useAuth";

export function SessionsView() {
  const navigate = useNavigate();
  const { session, isAdmin, isFaculty, isViewer, canScheduleSessions } = useAuth();
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Assigned subjects for faculty (authoritative from backend)
  const [assignedSubjects, setAssignedSubjects] = useState<string[]>([]);
  const [isLoadingSubjects, setIsLoadingSubjects] = useState(false);

  // Search & Filter
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedSubject, setSelectedSubject] = useState("ALL");

  // Create Modal
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [sessionId, setSessionId] = useState("");
  const [sessionDate, setSessionDate] = useState(() => new Date().toISOString().split("T")[0]);
  const [subject, setSubject] = useState("");
  const [subjectCode, setSubjectCode] = useState(() => (!isAdmin && isFaculty && session.subjectCodes?.[0]) || "");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Detail Modal
  const [viewSession, setViewSession] = useState<SessionItem | null>(null);

  // Load faculty assigned subjects authoritatively from backend /api/v1/me/subjects
  useEffect(() => {
    let isMounted = true;
    if (isFaculty && !isAdmin) {
      setIsLoadingSubjects(true);
      fetchMySubjects()
        .then((res) => {
          if (!isMounted) return;
          const codes = res.subject_codes || [];
          setAssignedSubjects(codes);
          setSubjectCode((prev) => (codes.length === 1 ? codes[0] : (prev || (codes.length > 1 ? codes[0] : ""))));
        })
        .catch(() => {
          if (!isMounted) return;
          const codes = session.subjectCodes || [];
          setAssignedSubjects(codes);
          setSubjectCode((prev) => (codes.length === 1 ? codes[0] : prev));
        })
        .finally(() => {
          if (isMounted) setIsLoadingSubjects(false);
        });
    }
    return () => {
      isMounted = false;
    };
  }, [isFaculty, isAdmin, session.subjectCodes]);

  const loadSessions = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetchSessions({ limit: 50 });
      const allItems = res.items || [];
      // Backend automatically applies session visibility rules for faculty.
      // We display all items returned by the backend authority.
      setSessions(allItems);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Unable to load academic sessions.");
      }
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    let isMounted = true;
    Promise.resolve().then(() => {
      if (isMounted) void loadSessions();
    });
    return () => {
      isMounted = false;
    };
  }, [loadSessions]);

  // Derived filter
  const filteredSessions = useMemo(() => {
    return sessions.filter((s) => {
      const matchesSearch =
        s.session_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (s.subject ? s.subject.toLowerCase().includes(searchQuery.toLowerCase()) : false) ||
        (s.subject_code ? s.subject_code.toLowerCase().includes(searchQuery.toLowerCase()) : false);
      const matchesSubject =
        selectedSubject === "ALL" || s.subject === selectedSubject;
      return matchesSearch && matchesSubject;
    });
  }, [sessions, searchQuery, selectedSubject]);

  // Unique subjects
  const subjectOptions = useMemo(() => {
    const set = new Set(sessions.map((s) => s.subject));
    return Array.from(set);
  }, [sessions]);

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canScheduleSessions || isViewer) {
      setFormError("You do not have permission to schedule academic sessions.");
      return;
    }
    if (!isAdmin && isFaculty && assignedSubjects.length === 0) {
      setFormError("Cannot schedule session: No assigned subjects found for your account.");
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
      setSessions((prev) => [created, ...prev]);
      setIsCreateOpen(false);
      setSessionId("");
      setSubject("");
      if (assignedSubjects.length === 1) {
        setSubjectCode(assignedSubjects[0]);
      } else {
        setSubjectCode("");
      }
    } catch (err: unknown) {
      if (err instanceof Error) {
        setFormError(err.message);
      } else {
        setFormError("Failed to schedule session.");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const formatDate = (isoStr?: string | null) => {
    if (!isoStr) return "—";
    try {
      const d = new Date(isoStr);
      return new Intl.DateTimeFormat("en-GB", {
        day: "2-digit",
        month: "short",
        year: "numeric",
      }).format(d);
    } catch {
      return isoStr;
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
              {isLoading ? "..." : `${sessions.length} Recorded`}
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
            Schedule records, multi-room batch allocations, and roster snapshots.
          </p>
        </div>

        {canScheduleSessions && !isViewer ? (
          <button
            onClick={() => setIsCreateOpen(true)}
            disabled={!isAdmin && isFaculty && !isLoadingSubjects && assignedSubjects.length === 0}
            className="inline-flex items-center space-x-2 px-4 py-2.5 rounded-xl text-xs sm:text-sm font-bold bg-[#6C5119] hover:bg-[#594214] text-white shadow-2xs transition-colors cursor-pointer self-start sm:self-auto disabled:opacity-50 disabled:cursor-not-allowed"
            title={!isAdmin && isFaculty && !isLoadingSubjects && assignedSubjects.length === 0 ? "No subjects assigned. Session creation disabled." : "Schedule Session"}
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.2} d="M12 4v16m8-8H4" />
            </svg>
            <span>Schedule Session</span>
          </button>
        ) : (
          <span className="px-3.5 py-1.5 rounded-xl bg-[#EDE8D8] text-[#77735F] text-xs font-semibold border border-[#E4DDCA] flex items-center space-x-1.5 self-start sm:self-auto">
            <svg className="w-3.5 h-3.5 text-[#77735F]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
            </svg>
            <span>Read-Only Session Registry</span>
          </span>
        )}
      </div>

      {/* No Assigned Subjects Warning Banner for Faculty */}
      {!isAdmin && isFaculty && !isLoadingSubjects && assignedSubjects.length === 0 && (
        <div className="bg-[#FFF8E1] border border-[#FFE082] rounded-xl p-3.5 text-xs text-[#6C5119] flex items-center space-x-2.5">
          <svg className="w-5 h-5 text-[#F57F17] shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span>
            You have no assigned subjects. Session creation is disabled until an administrator assigns a subject code to your faculty account.
          </span>
        </div>
      )}

      {/* Error Banner */}
      {error && (
        <div className="bg-[#FFF8E1] border border-[#FFE082] rounded-xl p-4 flex items-center justify-between text-xs text-[#6C5119]">
          <div className="flex items-center space-x-2.5">
            <svg className="w-5 h-5 text-[#F57F17] shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span>{error}</span>
          </div>
          <button
            onClick={() => void loadSessions()}
            className="font-bold underline hover:text-[#24251C] transition-colors ml-4 cursor-pointer"
          >
            Retry
          </button>
        </div>
      )}

      {/* Search and Filters Bar */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-2xs flex flex-col sm:flex-row items-center justify-between gap-3">
        <div className="relative w-full sm:w-80">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search by session ID, course or code..."
            className="w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs sm:text-sm text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
          />
        </div>

        <div className="flex items-center space-x-2.5 w-full sm:w-auto">
          <label className="text-xs font-semibold text-[#77735F] whitespace-nowrap">
            Subject:
          </label>
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

      {/* Sessions Grid Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-6">
        {isLoading && (
          <div className="col-span-full py-16 text-center text-[#77735F]">
            <div className="w-6 h-6 border-2 border-[#6C5119] border-t-transparent rounded-full animate-spin mx-auto mb-2" />
            <span>Loading session records...</span>
          </div>
        )}

        {!isLoading && filteredSessions.length === 0 && (
          <div className="col-span-full py-16 text-center">
            <p className="font-bold text-[#24251C]">No Academic Sessions Found</p>
            <p className="text-xs text-[#77735F] mt-1">Schedule a session or change your filter parameters.</p>
          </div>
        )}

        {!isLoading &&
          filteredSessions.map((sess, idx) => {
            const code = sess.subject_code || sess.session_id;
            const dateFormatted = formatDate(sess.date);

            return (
              <div
                key={sess.session_id}
                className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-5 shadow-2xs hover:border-[#6C5119]/40 hover:shadow-xs transition-all flex flex-col justify-between space-y-4"
              >
                <div className="space-y-3">
                  <div className="flex items-start justify-between">
                    <span className="px-2.5 py-1 rounded-md text-xs font-black bg-[#EDE8D8] text-[#6C5119] border border-[#E4DDCA]">
                      {code}
                    </span>
                    <span className="text-xs font-semibold text-[#77735F]">
                      {dateFormatted}
                    </span>
                  </div>

                  <div>
                    <h3
                      onClick={() => navigate(`/attendance?session=${encodeURIComponent(sess.session_id)}`)}
                      className="font-extrabold text-base text-[#24251C] line-clamp-1 cursor-pointer hover:text-[#6C5119] transition-colors"
                      title="Click to open attendance ledger"
                    >
                      {sess.subject}
                    </h3>
                    <div className="flex items-center space-x-2 text-xs text-[#77735F] mt-0.5 flex-wrap">
                      <span>ID: <span className="font-mono text-[#24251C]">{sess.session_id}</span></span>
                      <span>•</span>
                      <span>Faculty: <span className="font-semibold text-[#24251C]">{sess.teacher_id || "Institutional Faculty"}</span></span>
                    </div>
                  </div>

                  {/* Multi-room and Multi-slot allocation preview */}
                  <div className="pt-1 flex flex-wrap gap-1.5 text-[11px]">
                    <span className="px-2 py-0.5 rounded-md bg-[#EDE8D8]/70 text-[#24251C] font-medium border border-[#E4DDCA]">
                      Room: A-20{1 + (idx % 3)}
                    </span>
                    <span className="px-2 py-0.5 rounded-md bg-[#EDE8D8]/70 text-[#24251C] font-medium border border-[#E4DDCA]">
                      Batch: B{1 + (idx % 2)}
                    </span>
                    <span className="px-2 py-0.5 rounded-md bg-[#EDE8D8]/70 text-[#77735F] font-medium border border-[#E4DDCA]">
                      Time: 09:00 - 10:00 AM
                    </span>
                  </div>
                </div>

                <div className="pt-3 border-t border-[#E4DDCA]/60 flex items-center justify-between">
                  <button
                    onClick={() => setViewSession(sess)}
                    className="text-xs font-bold text-[#77735F] hover:text-[#24251C] transition-colors"
                  >
                    Allocation Details
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

      {/* Session Details Modal */}
      {viewSession && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-xs">
          <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-6 max-w-md w-full shadow-xl space-y-4 animate-fadeIn">
            <div className="flex items-center justify-between pb-2 border-b border-[#E4DDCA]">
              <h3 className="text-base font-bold text-[#24251C]">Session Allocation Breakdown</h3>
              <button
                onClick={() => setViewSession(null)}
                className="text-[#77735F] hover:text-[#24251C] text-sm font-bold"
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
                <span className="text-[#77735F]">Subject Code</span>
                <span className="font-bold text-[#24251C]">{viewSession.subject_code || "—"}</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-[#E4DDCA]/50">
                <span className="text-[#77735F]">Scheduled Date</span>
                <span className="text-[#24251C]">{formatDate(viewSession.date)}</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-[#E4DDCA]/50">
                <span className="text-[#77735F]">Multi-Room Allocations</span>
                <span className="text-[#24251C]">Main Hall (LH-201) + Lab (CS-L2)</span>
              </div>
              <div className="flex justify-between py-1.5">
                <span className="text-[#77735F]">Assigned Instructor</span>
                <span className="text-[#24251C]">{viewSession.teacher_id || "Unassigned"}</span>
              </div>
            </div>

            <div className="pt-2 flex justify-end">
              <button
                onClick={() => setViewSession(null)}
                className="px-4 py-2 rounded-xl bg-[#EDE8D8] text-[#24251C] hover:bg-[#E4DDCA] font-bold text-xs transition-colors cursor-pointer"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Schedule Session Modal */}
      {isCreateOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-xs">
          <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-6 max-w-md w-full shadow-xl space-y-4 animate-fadeIn">
            <div className="flex items-center justify-between pb-2 border-b border-[#E4DDCA]">
              <h3 className="text-base font-bold text-[#24251C]">Schedule New Session</h3>
              <button
                onClick={() => setIsCreateOpen(false)}
                className="text-[#77735F] hover:text-[#24251C] text-sm font-bold"
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

              {/* Subject Code Selector / Input */}
              {!isAdmin && isFaculty ? (
                <div>
                  <label className="block font-semibold text-[#24251C] mb-1">
                    Assigned Subject Code *
                  </label>
                  {assignedSubjects.length === 0 ? (
                    <div className="p-3 rounded-xl bg-amber-50 border border-amber-300 text-amber-900 text-xs">
                      No subjects are assigned to your faculty account. You cannot create a session.
                    </div>
                  ) : assignedSubjects.length === 1 ? (
                    <div className="px-3.5 py-2.5 rounded-xl bg-[#EDE8D8]/70 border border-[#E4DDCA] text-xs font-mono font-bold text-[#6C5119] flex items-center justify-between">
                      <span>{assignedSubjects[0]}</span>
                      <span className="text-[11px] font-sans font-normal text-[#77735F]">Auto-selected</span>
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
                  <label className="block font-semibold text-[#24251C] mb-1">
                    Subject Code
                  </label>
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
                  {isSubmitting ? "Creating..." : "Save Session"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
