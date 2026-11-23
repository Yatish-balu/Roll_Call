import React, { useState, useEffect, useCallback, useMemo } from "react";
import {
  fetchInvigilationSession,
  submitFormB,
  scanSignedSheetAi,
  type InvigilationSession,
  type StudentExamRosterItem,
  type ExamCandidateStatus,
  type ScanSignedSheetResult,
} from "@/services/api/exams";
import { FormBTimer } from "@/features/exams/components/FormBTimer";

export function InvigilatorFormBView() {
  const [session, setSession] = useState<InvigilationSession | null>(null);
  const [roster, setRoster] = useState<StudentExamRosterItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Search & Filter
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"ALL" | "PRESENT" | "ABSENT">("ALL");

  // Timer & Submission Lock State
  const [isExpired, setIsExpired] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSubmitted, setIsSubmitted] = useState(false);
  const [submissionFeedback, setSubmissionFeedback] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  // AI Assist Scan Modal State
  const [isAiModalOpen, setIsAiModalOpen] = useState(false);
  const [aiScanFile, setAiScanFile] = useState<File | null>(null);
  const [isScanning, setIsScanning] = useState(false);
  const [scanResult, setScanResult] = useState<ScanSignedSheetResult | null>(null);

  // Load invigilation session
  const loadSession = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchInvigilationSession("A-201");
      setSession(data);
      setRoster(data.students);
      setIsSubmitted(data.is_submitted);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load invigilation roster.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSession();
  }, [loadSession]);

  // Handle individual student status toggle
  const toggleStudentStatus = (usn: string) => {
    if (isSubmitted || isExpired) return;

    setRoster((prev) =>
      prev.map((s) => {
        if (s.usn === usn) {
          const newStatus: ExamCandidateStatus = s.status === "PRESENT" ? "ABSENT" : "PRESENT";
          return { ...s, status: newStatus };
        }
        return s;
      })
    );
  };

  // Mark all present
  const markAllPresent = () => {
    if (isSubmitted || isExpired) return;
    setRoster((prev) => prev.map((s) => ({ ...s, status: "PRESENT" })));
  };

  // Counts for live footer
  const totalCount = roster.length;
  const presentCount = roster.filter((s) => s.status === "PRESENT").length;
  const absentCount = roster.filter((s) => s.status === "ABSENT").length;
  const attendancePercentage = totalCount > 0 ? ((presentCount / totalCount) * 100).toFixed(1) : "0.0";

  // Filtered roster for table view
  const filteredRoster = useMemo(() => {
    return roster.filter((s) => {
      const matchesSearch =
        s.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        s.usn.toLowerCase().includes(searchQuery.toLowerCase()) ||
        s.branch.toLowerCase().includes(searchQuery.toLowerCase());
      if (!matchesSearch) return false;

      if (statusFilter === "PRESENT") return s.status === "PRESENT";
      if (statusFilter === "ABSENT") return s.status === "ABSENT";
      return true;
    });
  }, [roster, searchQuery, statusFilter]);

  // Submit Form-B
  const handleSubmitFormB = async () => {
    if (!session) return;
    if (isSubmitted) return;
    if (isExpired) {
      setSubmissionFeedback({
        type: "error",
        text: "The Form-B submission deadline has expired. Please contact the Exam Cell directly.",
      });
      return;
    }

    const confirmSubmit = window.confirm(
      `Confirm Form-B Submission for Room ${session.room.room_id}?\n\nPresent: ${presentCount}\nAbsent: ${absentCount}\nTotal: ${totalCount}\n\nOnce submitted, the record is locked for the Exam Cell.`
    );
    if (!confirmSubmit) return;

    setIsSubmitting(true);
    setSubmissionFeedback(null);
    try {
      const payload = roster.map((s) => ({ usn: s.usn, status: s.status }));
      const res = await submitFormB(session.exam.id, session.room.room_id, payload);
      setIsSubmitted(true);
      setSubmissionFeedback({
        type: "success",
        text: `${res.message} Submission recorded at ${new Date(res.submitted_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}.`,
      });
    } catch (err) {
      setSubmissionFeedback({
        type: "error",
        text: err instanceof Error ? err.message : "Failed to submit Form-B.",
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  // AI Assist Scan Submit
  const handleAiScan = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!aiScanFile || !session) return;

    setIsScanning(true);
    try {
      const result = await scanSignedSheetAi(aiScanFile, session.room.room_id);
      setScanResult(result);
    } catch (err) {
      alert(err instanceof Error ? err.message : "AI Scan failed. Please retry.");
    } finally {
      setIsScanning(false);
    }
  };

  // Apply AI Scan Detections to roster
  const handleApplyAiResults = () => {
    if (!scanResult) return;

    setRoster((prev) =>
      prev.map((s) => {
        if (scanResult.detected_absentees.includes(s.usn)) {
          return { ...s, status: "ABSENT" };
        }
        return { ...s, status: "PRESENT" };
      })
    );

    setIsAiModalOpen(false);
    setScanResult(null);
    setAiScanFile(null);
    setSubmissionFeedback({
      type: "success",
      text: `AI Assist applied! ${scanResult.detected_absentees.length} absentees detected and synchronized.`,
    });
  };

  if (isLoading) {
    return (
      <div className="bg-[#FBF8F0] dark:bg-[#181913] border border-[#E4DDCA] dark:border-[#2C3022] rounded-2xl p-16 text-center text-[#77735F]">
        <div className="inline-block animate-spin w-8 h-8 border-3 border-[#3F451F] border-t-transparent rounded-full mb-3" />
        <p className="text-sm font-semibold">Loading Invigilation Form-B roster...</p>
      </div>
    );
  }

  if (error || !session) {
    return (
      <div className="bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900 rounded-2xl p-8 text-center space-y-3">
        <p className="text-sm text-red-700 dark:text-red-300 font-semibold">
          {error || "No invigilation duty assigned for this faculty account."}
        </p>
        <button
          onClick={() => void loadSession()}
          className="px-4 py-2 bg-[#3F451F] text-[#FBF8F0] text-xs font-bold rounded-xl cursor-pointer"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6 pb-24">
      {/* Header Bar */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-xs font-extrabold px-2.5 py-0.5 rounded-md bg-[#EDE8D8] dark:bg-[#2C3117] text-[#6C5119] dark:text-[#D2A847] border border-[#E4DDCA] dark:border-[#2C3022]">
              FORM-B DIGITAL REGISTER
            </span>
            <span className="text-xs font-bold text-[#77735F] dark:text-[#A9AE8C]">
              Invigilator: {session.room.invigilator_name}
            </span>
          </div>

          {/* Header specification: "My Invigilation · Room X", exam name, course code, date, time */}
          <h1 className="text-2xl sm:text-3xl font-black text-[#24251C] dark:text-[#EDE8D8] tracking-tight mt-1">
            My Invigilation · {session.room.room_id}
          </h1>
          <p className="text-xs sm:text-sm font-semibold text-[#6C5119] dark:text-[#D2A847] mt-0.5">
            {session.exam.title} · {session.exam.course_code} ({session.exam.course_name || "Exam"}) · {session.exam.date} · {session.exam.time}
          </p>
        </div>

        {/* Action Button: [Scan Signed Sheet (AI Assist)] */}
        <div className="flex items-center gap-3">
          <button
            type="button"
            disabled={isSubmitted || isExpired}
            onClick={() => setIsAiModalOpen(true)}
            className="inline-flex items-center justify-center gap-2 px-4 py-2.5 bg-[#6C5119] text-[#FBF8F0] text-xs font-bold rounded-xl hover:bg-[#584213] transition-all shadow-sm disabled:opacity-50 cursor-pointer"
          >
            <svg className="w-4 h-4 text-amber-200" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            Scan Signed Sheet (AI Assist)
          </button>
        </div>
      </div>

      {/* Form-B Timer Countdown */}
      <FormBTimer
        deadline={session.deadline}
        totalDurationSeconds={1800}
        onExpire={() => setIsExpired(true)}
      />

      {/* Submission Feedback Banner */}
      {submissionFeedback && (
        <div
          className={`p-4 rounded-2xl border flex items-center justify-between gap-3 text-xs font-medium animate-in fade-in duration-200 ${
            submissionFeedback.type === "success"
              ? "bg-emerald-50 border-emerald-300 text-emerald-800 dark:bg-emerald-950/40 dark:border-emerald-800 dark:text-emerald-300"
              : "bg-red-50 border-red-300 text-red-800 dark:bg-red-950/40 dark:border-red-800 dark:text-red-300"
          }`}
        >
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-500 shrink-0" />
            <span>{submissionFeedback.text}</span>
          </div>
          <button
            onClick={() => setSubmissionFeedback(null)}
            className="text-xs font-bold hover:underline cursor-pointer"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Submitted Status Banner */}
      {isSubmitted && (
        <div className="bg-emerald-100/70 dark:bg-emerald-950/50 border border-emerald-300 dark:border-emerald-800 rounded-2xl p-4 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-xl bg-emerald-600 text-white flex items-center justify-center font-bold">
              ✓
            </div>
            <div>
              <p className="text-sm font-extrabold text-emerald-900 dark:text-emerald-200">
                Form-B Official Attendance Submitted & Locked
              </p>
              <p className="text-xs text-emerald-700 dark:text-emerald-400">
                Data recorded for Room {session.room.room_id}. The Exam Cell has received the final absentee list.
              </p>
            </div>
          </div>
          <span className="px-3 py-1 rounded-full text-[10px] font-black uppercase tracking-wider bg-emerald-600 text-white shrink-0">
            RECORD LOCKED
          </span>
        </div>
      )}

      {/* Roster Controls & Search Filter */}
      <div className="bg-[#FBF8F0] dark:bg-[#181913] border border-[#E4DDCA] dark:border-[#2C3022] rounded-2xl p-4 shadow-sm flex flex-col md:flex-row items-stretch md:items-center justify-between gap-3">
        <div className="flex-1 relative">
          <input
            type="text"
            placeholder="Search student by USN, Name, or Branch..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-[#F2EDE0] dark:bg-[#11120D] border border-[#E4DDCA] dark:border-[#2C3022] rounded-xl px-4 py-2.5 text-xs text-[#24251C] dark:text-[#EDE8D8] placeholder-[#77735F] focus:outline-none focus:border-[#3F451F]"
          />
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {(["ALL", "PRESENT", "ABSENT"] as const).map((filter) => (
            <button
              key={filter}
              type="button"
              onClick={() => setStatusFilter(filter)}
              className={`px-3 py-2 rounded-xl text-xs font-bold tracking-wide transition-all cursor-pointer ${
                statusFilter === filter
                  ? "bg-[#3F451F] text-[#FBF8F0]"
                  : "bg-[#F2EDE0] dark:bg-[#11120D] text-[#77735F] dark:text-[#A9AE8C] hover:bg-[#EAE4D4]"
              }`}
            >
              {filter === "ALL" ? `All (${roster.length})` : filter === "PRESENT" ? `Present (${presentCount})` : `Absent (${absentCount})`}
            </button>
          ))}

          {!isSubmitted && !isExpired && (
            <button
              type="button"
              onClick={markAllPresent}
              className="px-3 py-2 rounded-xl text-xs font-bold bg-[#EDE8D8] dark:bg-[#2C3117] text-[#6C5119] dark:text-[#D2A847] hover:bg-[#E4DDCA] transition-colors cursor-pointer"
            >
              Mark All Present
            </button>
          )}
        </div>
      </div>

      {/* Student Roster Table */}
      <div className="bg-[#FBF8F0] dark:bg-[#181913] border border-[#E4DDCA] dark:border-[#2C3022] rounded-2xl overflow-hidden shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-[#F2EDE0] dark:bg-[#11120D] text-[#77735F] dark:text-[#A9AE8C] uppercase text-xs border-b border-[#E4DDCA] dark:border-[#2C3022]">
              <tr>
                <th className="py-3 px-4 font-bold w-16">Sl</th>
                <th className="py-3 px-4 font-bold">USN</th>
                <th className="py-3 px-4 font-bold">Candidate Name</th>
                <th className="py-3 px-4 font-bold">Branch</th>
                <th className="py-3 px-4 font-bold">Desk</th>
                <th className="py-3 px-4 font-bold text-center">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#E4DDCA]/60 dark:divide-[#2C3022] text-[#24251C] dark:text-[#EDE8D8]">
              {filteredRoster.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-xs text-[#77735F]">
                    No students match the search criteria.
                  </td>
                </tr>
              ) : (
                filteredRoster.map((student) => {
                  const isPresent = student.status === "PRESENT";
                  return (
                    <tr
                      key={student.usn}
                      className={`transition-colors ${
                        !isPresent
                          ? "bg-rose-50/60 dark:bg-rose-950/20"
                          : "hover:bg-[#F2EDE0]/40 dark:hover:bg-[#2C3117]/20"
                      }`}
                    >
                      <td className="py-3 px-4 font-mono text-xs font-semibold text-[#77735F]">
                        {student.sl}
                      </td>
                      <td className="py-3 px-4 font-mono font-bold text-[#3F451F] dark:text-[#D2A847]">
                        {student.usn}
                      </td>
                      <td className="py-3 px-4 font-semibold">{student.name}</td>
                      <td className="py-3 px-4">
                        <span className="font-mono text-xs font-bold px-2 py-0.5 rounded bg-[#EDE8D8] dark:bg-[#2C3117] text-[#6C5119] dark:text-[#D2A847] border border-[#E4DDCA] dark:border-[#2C3022]">
                          {student.branch}
                        </span>
                      </td>
                      <td className="py-3 px-4 font-mono text-xs text-[#77735F]">
                        {student.seat_number || "—"}
                      </td>
                      <td className="py-3 px-4 text-center">
                        {/* Status Toggle (Present/Absent Checkbox toggle, default Present) */}
                        <label className="inline-flex items-center gap-2 cursor-pointer select-none">
                          <input
                            type="checkbox"
                            checked={isPresent}
                            disabled={isSubmitted || isExpired}
                            onChange={() => toggleStudentStatus(student.usn)}
                            className="w-4 h-4 text-[#3F451F] rounded accent-[#3F451F] focus:ring-0 disabled:opacity-50 cursor-pointer"
                          />
                          <span
                            className={`px-2.5 py-0.5 rounded-full text-[11px] font-black uppercase tracking-wider border ${
                              isPresent
                                ? "bg-emerald-100 text-emerald-800 border-emerald-200 dark:bg-emerald-950/50 dark:text-emerald-300 dark:border-emerald-800"
                                : "bg-rose-100 text-rose-800 border-rose-200 dark:bg-rose-950/50 dark:text-rose-300 dark:border-rose-800"
                            }`}
                          >
                            {student.status}
                          </span>
                        </label>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Live Sticky Footer: Present / Absent / Total Counts & [Submit Form-B] */}
      <div className="fixed bottom-0 left-0 right-0 z-40 bg-[#FBF8F0]/95 dark:bg-[#181913]/95 backdrop-blur-md border-t border-[#E4DDCA] dark:border-[#2C3022] px-4 py-3 sm:px-8 shadow-2xl">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-3">
          {/* Live Counts: Present / Absent / Total counts */}
          <div className="flex items-center gap-4 sm:gap-6 text-xs sm:text-sm font-bold flex-wrap">
            <span className="flex items-center gap-1.5 text-emerald-700 dark:text-emerald-400">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
              Present: <strong className="font-mono text-base">{presentCount}</strong>
            </span>
            <span className="flex items-center gap-1.5 text-rose-600 dark:text-rose-400">
              <span className="w-2.5 h-2.5 rounded-full bg-rose-500" />
              Absent: <strong className="font-mono text-base">{absentCount}</strong>
            </span>
            <span className="flex items-center gap-1.5 text-[#24251C] dark:text-[#EDE8D8]">
              Total Candidates: <strong className="font-mono text-base">{totalCount}</strong>
            </span>
            <span className="text-xs font-mono font-bold text-[#6C5119] dark:text-[#D2A847] bg-[#EDE8D8] dark:bg-[#2C3117] px-2 py-0.5 rounded-md border border-[#E4DDCA] dark:border-[#2C3022]">
              {attendancePercentage}% Turnout
            </span>
          </div>

          {/* Action: [Submit Form-B] Button (disabled after deadline or submission) */}
          <div className="flex items-center gap-3">
            <button
              type="button"
              disabled={isSubmitting || isSubmitted || isExpired}
              onClick={handleSubmitFormB}
              className="inline-flex items-center justify-center gap-2 px-6 py-2.5 bg-[#3F451F] text-[#FBF8F0] text-xs sm:text-sm font-black rounded-xl hover:bg-[#323719] transition-all shadow-md disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
              </svg>
              {isSubmitting
                ? "Submitting Form-B..."
                : isSubmitted
                ? "Form-B Submitted (Locked)"
                : isExpired
                ? "Form-B Closed"
                : "Submit Form-B"}
            </button>
          </div>
        </div>
      </div>

      {/* AI Assist Scanner Modal */}
      {isAiModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-[#FBF8F0] dark:bg-[#181913] border border-[#E4DDCA] dark:border-[#2C3022] rounded-2xl p-6 max-w-lg w-full shadow-2xl animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between pb-3 border-b border-[#E4DDCA] dark:border-[#2C3022]">
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded-md text-[10px] font-black uppercase bg-[#6C5119] text-[#FBF8F0]">
                  AI OCR ASSIST
                </span>
                <h3 className="text-lg font-extrabold text-[#24251C] dark:text-[#EDE8D8]">
                  Scan Signed Sheet
                </h3>
              </div>
              <button
                type="button"
                onClick={() => {
                  setIsAiModalOpen(false);
                  setScanResult(null);
                }}
                className="text-[#77735F] hover:text-[#24251C] p-1 rounded-lg"
              >
                ✕
              </button>
            </div>

            {!scanResult ? (
              <form onSubmit={handleAiScan} className="mt-4 space-y-4">
                <p className="text-xs text-[#77735F] dark:text-[#A9AE8C]">
                  Take a photo or upload an image of the signed attendance sheet for Room {session.room.room_id}. The AI will detect candidate signatures and identify absentees automatically.
                </p>

                <div className="border-2 border-dashed border-[#E4DDCA] dark:border-[#2C3022] rounded-xl p-6 text-center hover:bg-[#F2EDE0]/50 transition-colors">
                  <svg className="w-10 h-10 text-[#6C5119] dark:text-[#D2A847] mx-auto mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
                  </svg>
                  <input
                    type="file"
                    accept="image/*"
                    onChange={(e) => setAiScanFile(e.target.files?.[0] || null)}
                    className="block w-full text-xs text-[#77735F] file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-bold file:bg-[#3F451F] file:text-[#FBF8F0] hover:file:bg-[#323719] file:cursor-pointer cursor-pointer"
                  />
                  {aiScanFile && (
                    <p className="mt-2 text-xs font-mono font-bold text-emerald-700 dark:text-emerald-400">
                      File: {aiScanFile.name} ({(aiScanFile.size / 1024).toFixed(1)} KB)
                    </p>
                  )}
                </div>

                <div className="pt-2 flex items-center justify-end gap-2.5">
                  <button
                    type="button"
                    onClick={() => setIsAiModalOpen(false)}
                    className="px-4 py-2 rounded-xl text-xs font-bold text-[#77735F] hover:bg-[#F2EDE0] dark:hover:bg-[#2C3117] transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={!aiScanFile || isScanning}
                    className="px-5 py-2 rounded-xl text-xs font-bold bg-[#6C5119] text-[#FBF8F0] hover:bg-[#584213] transition-colors disabled:opacity-50 cursor-pointer"
                  >
                    {isScanning ? "Analyzing Sheet via AI..." : "Scan & Detect Absentees"}
                  </button>
                </div>
              </form>
            ) : (
              <div className="mt-4 space-y-4">
                <div className="p-3 bg-emerald-50 border border-emerald-200 dark:bg-emerald-950/40 dark:border-emerald-800 rounded-xl">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-extrabold text-emerald-800 dark:text-emerald-300">
                      Scan Completed Successfully
                    </span>
                    <span className="font-mono text-xs font-bold text-emerald-700 dark:text-emerald-400">
                      Confidence: {(scanResult.confidence * 100).toFixed(1)}%
                    </span>
                  </div>
                  <p className="text-xs text-emerald-700 dark:text-emerald-400 mt-1">
                    AI detected {scanResult.detected_absentees.length} un-signed / empty signature boxes.
                  </p>
                </div>

                <div>
                  <h4 className="text-xs font-bold text-[#24251C] dark:text-[#EDE8D8] uppercase tracking-wider mb-2">
                    Detected Absentee Candidates:
                  </h4>
                  <div className="space-y-1.5 max-h-48 overflow-y-auto">
                    {scanResult.detected_absentees.map((usn) => {
                      const student = roster.find((s) => s.usn === usn);
                      return (
                        <div
                          key={usn}
                          className="flex items-center justify-between p-2 rounded-lg bg-rose-50 border border-rose-200 dark:bg-rose-950/30 dark:border-rose-800 text-xs"
                        >
                          <span className="font-mono font-bold text-rose-800 dark:text-rose-300">{usn}</span>
                          <span className="font-semibold text-[#24251C] dark:text-[#EDE8D8]">{student?.name || "Student"}</span>
                          <span className="font-mono text-[10px] text-rose-600 font-bold uppercase">NO SIGNATURE</span>
                        </div>
                      );
                    })}
                  </div>
                </div>

                <div className="pt-3 border-t border-[#E4DDCA] dark:border-[#2C3022] flex items-center justify-end gap-2.5">
                  <button
                    type="button"
                    onClick={() => setScanResult(null)}
                    className="px-4 py-2 rounded-xl text-xs font-bold text-[#77735F] hover:bg-[#F2EDE0] dark:hover:bg-[#2C3117] transition-colors"
                  >
                    Rescan
                  </button>
                  <button
                    type="button"
                    onClick={handleApplyAiResults}
                    className="px-5 py-2 rounded-xl text-xs font-bold bg-[#3F451F] text-[#FBF8F0] hover:bg-[#323719] transition-colors cursor-pointer"
                  >
                    Apply AI Detections to Roster
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
