import React, { useState, useEffect, useCallback, useMemo } from "react";
import {
  fetchActiveExam,
  createExam,
  uploadSeatingCsv,
  downloadFormBAbsenteesPdf,
  downloadRoomSignSheets,
  type ActiveExamDetails,
  type CreateExamParams,
} from "@/services/api/exams";
import { RoomCard } from "@/features/exams/components/RoomCard";
import { BranchSummaryTable } from "@/features/exams/components/BranchSummaryTable";

export function ExamControlView() {
  const [data, setData] = useState<ActiveExamDetails | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // Filter state for rooms
  const [roomFilter, setRoomFilter] = useState<"ALL" | "OPEN" | "SUBMITTED" | "SCHEDULED">("ALL");

  // Create Exam Modal State
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [createForm, setCreateForm] = useState<CreateExamParams>({
    title: "",
    sem: "Sem 7",
    branch: "CY",
    course_code: "",
    course_name: "",
    date: new Date().toISOString().split("T")[0],
    time: "10:00-11:30 AM",
  });

  // Upload Seating Modal State
  const [isUploadOpen, setIsUploadOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);

  // Download loading states
  const [isDownloadingPdf, setIsDownloadingPdf] = useState(false);
  const [isDownloadingSheets, setIsDownloadingSheets] = useState(false);

  // Load active exam details
  const loadExamDetails = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const activeData = await fetchActiveExam();
      setData(activeData);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load active exam data.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadExamDetails();
  }, [loadExamDetails]);

  // Filter rooms
  const filteredRooms = useMemo(() => {
    if (!data?.rooms) return [];
    if (roomFilter === "ALL") return data.rooms;
    return data.rooms.filter((r) => r.status === roomFilter);
  }, [data?.rooms, roomFilter]);

  // Helper to trigger file download in browser
  const triggerDownload = (blob: Blob, filename: string) => {
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);
  };

  // Download Form-B Absentees PDF
  const handleDownloadFormBPdf = async () => {
    if (!data?.exam) return;
    setIsDownloadingPdf(true);
    try {
      const blob = await downloadFormBAbsenteesPdf(data.exam.id);
      triggerDownload(blob, `Form-B-Absentees-${data.exam.course_code}.txt`);
      setFeedback({ type: "success", text: "Form-B Absentees report generated and downloaded successfully." });
    } catch (err) {
      setFeedback({
        type: "error",
        text: err instanceof Error ? err.message : "Failed to download Form-B report.",
      });
    } finally {
      setIsDownloadingPdf(false);
    }
  };

  // Download Room Sign Sheets
  const handleDownloadRoomSheets = async () => {
    if (!data?.exam) return;
    setIsDownloadingSheets(true);
    try {
      const blob = await downloadRoomSignSheets(data.exam.id);
      triggerDownload(blob, `Room-Sign-Sheets-${data.exam.course_code}.txt`);
      setFeedback({ type: "success", text: "Room Signature verification sheets downloaded successfully." });
    } catch (err) {
      setFeedback({
        type: "error",
        text: err instanceof Error ? err.message : "Failed to download sign sheets.",
      });
    } finally {
      setIsDownloadingSheets(false);
    }
  };

  // Create New Exam submit
  const handleCreateExamSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!createForm.title || !createForm.course_code) {
      setFeedback({ type: "error", text: "Please enter an Exam Title and Course Code." });
      return;
    }

    setIsCreating(true);
    try {
      await createExam(createForm);
      setIsCreateOpen(false);
      setFeedback({ type: "success", text: `Exam "${createForm.title}" scheduled successfully!` });
      await loadExamDetails();
    } catch (err) {
      setFeedback({
        type: "error",
        text: err instanceof Error ? err.message : "Failed to create new exam.",
      });
    } finally {
      setIsCreating(false);
    }
  };

  // Upload Seating CSV submit
  const handleUploadSeatingSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile) {
      setFeedback({ type: "error", text: "Please select a valid CSV file to upload." });
      return;
    }

    setIsUploading(true);
    try {
      const res = await uploadSeatingCsv(selectedFile);
      setIsUploadOpen(false);
      setSelectedFile(null);
      setFeedback({ type: "success", text: res.message });
      await loadExamDetails();
    } catch (err) {
      setFeedback({
        type: "error",
        text: err instanceof Error ? err.message : "Failed to upload seating CSV.",
      });
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="px-2.5 py-0.5 rounded-md text-[10px] font-black uppercase tracking-wider bg-[#3F451F] text-[#FBF8F0]">
              CONTROLLER OF EXAMINATIONS
            </span>
            <span className="text-xs font-semibold text-[#77735F] dark:text-[#A9AE8C]">
              Continuous Internal Evaluation (CIE)
            </span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-[#24251C] dark:text-[#EDE8D8] tracking-tight mt-1">
            Exam Cell Control Dashboard
          </h1>
          <p className="text-xs sm:text-sm text-[#77735F] dark:text-[#A9AE8C] mt-0.5">
            Real-time hall allocations, invigilator Form-B synchronization, and absentee consolidation.
          </p>
        </div>

        {/* Action Buttons: [Create New Exam], [Upload Seating CSV] */}
        <div className="flex items-center gap-2.5 flex-wrap">
          <button
            type="button"
            onClick={() => setIsUploadOpen(true)}
            className="inline-flex items-center justify-center gap-2 px-3.5 py-2.5 bg-[#FBF8F0] dark:bg-[#181913] text-[#24251C] dark:text-[#EDE8D8] text-xs font-bold rounded-xl border border-[#E4DDCA] dark:border-[#2C3022] hover:bg-[#EDE8D8] dark:hover:bg-[#2C3117] transition-all shadow-xs cursor-pointer"
          >
            <svg className="w-4 h-4 text-[#6C5119] dark:text-[#D2A847]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
            </svg>
            Upload Seating CSV
          </button>

          <button
            type="button"
            onClick={() => setIsCreateOpen(true)}
            className="inline-flex items-center justify-center gap-2 px-4 py-2.5 bg-[#3F451F] text-[#FBF8F0] text-xs font-bold rounded-xl hover:bg-[#323719] transition-all shadow-sm cursor-pointer"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            Create New Exam
          </button>
        </div>
      </div>

      {/* Global Feedback Banner */}
      {feedback && (
        <div
          className={`p-3.5 rounded-xl border flex items-center justify-between gap-3 text-xs font-medium animate-in fade-in duration-200 ${
            feedback.type === "success"
              ? "bg-emerald-50 border-emerald-200 text-emerald-800 dark:bg-emerald-950/40 dark:border-emerald-800 dark:text-emerald-300"
              : "bg-red-50 border-red-200 text-red-800 dark:bg-red-950/40 dark:border-red-800 dark:text-red-300"
          }`}
        >
          <span>{feedback.text}</span>
          <button
            onClick={() => setFeedback(null)}
            className="text-xs font-bold hover:underline cursor-pointer"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Loading & Error States */}
      {isLoading ? (
        <div className="bg-[#FBF8F0] dark:bg-[#181913] border border-[#E4DDCA] dark:border-[#2C3022] rounded-2xl p-16 text-center text-[#77735F]">
          <div className="inline-block animate-spin w-8 h-8 border-3 border-[#3F451F] border-t-transparent rounded-full mb-3" />
          <p className="text-sm font-semibold">Loading live examination status...</p>
        </div>
      ) : error ? (
        <div className="bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900 rounded-2xl p-8 text-center space-y-3">
          <p className="text-sm text-red-700 dark:text-red-300 font-semibold">{error}</p>
          <button
            onClick={() => void loadExamDetails()}
            className="px-4 py-2 bg-[#3F451F] text-[#FBF8F0] text-xs font-bold rounded-xl hover:bg-[#323719] cursor-pointer"
          >
            Retry Loading
          </button>
        </div>
      ) : !data || !data.exam ? (
        <div className="bg-[#FBF8F0] dark:bg-[#181913] border border-[#E4DDCA] dark:border-[#2C3022] rounded-2xl p-12 text-center text-[#77735F]">
          <p className="text-sm font-semibold">No active examination session found.</p>
          <button
            onClick={() => setIsCreateOpen(true)}
            className="mt-4 px-4 py-2 bg-[#3F451F] text-[#FBF8F0] text-xs font-bold rounded-xl cursor-pointer"
          >
            Schedule Exam Now
          </button>
        </div>
      ) : (
        <>
          {/* Active Exam Card */}
          <div className="bg-[#FBF8F0] dark:bg-[#181913] border border-[#E4DDCA] dark:border-[#2C3022] rounded-2xl p-6 shadow-sm relative overflow-hidden">
            <div className="absolute top-0 right-0 bg-[#A77A13] text-white text-[10px] font-black uppercase tracking-wider px-3 py-1 rounded-bl-xl shadow-xs">
              LIVE EXAMINATION
            </div>

            <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-6">
              <div className="space-y-2">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-mono text-xs font-extrabold px-2.5 py-0.5 rounded-md bg-[#EDE8D8] dark:bg-[#2C3117] text-[#6C5119] dark:text-[#D2A847] border border-[#E4DDCA] dark:border-[#2C3022]">
                    {data.exam.course_code}
                  </span>
                  <span className="text-xs font-bold text-[#77735F] dark:text-[#A9AE8C]">
                    {data.exam.sem} · Branch: {data.exam.branch}
                  </span>
                </div>

                <h2 className="text-xl sm:text-2xl font-black text-[#24251C] dark:text-[#EDE8D8] tracking-tight">
                  {data.exam.title}
                </h2>

                {/* Specified format: "CIE-III November 2026 · Sem 7 · CY · 22CY72 · 02-Nov-2026 · 10:00-11:30 AM" */}
                <p className="text-xs sm:text-sm font-semibold text-[#6C5119] dark:text-[#D2A847] flex items-center gap-2 flex-wrap">
                  <span>{data.exam.title} · {data.exam.sem} · {data.exam.branch} · {data.exam.course_code} · {data.exam.date} · {data.exam.time}</span>
                </p>
              </div>

              {/* Quick Metric Badges */}
              <div className="grid grid-cols-3 gap-3 border-t lg:border-t-0 lg:border-l border-[#E4DDCA] dark:border-[#2C3022] pt-4 lg:pt-0 lg:pl-6 shrink-0">
                <div className="text-center px-2">
                  <p className="text-[10px] uppercase font-bold text-[#77735F] dark:text-[#A9AE8C]">Total Seated</p>
                  <p className="text-2xl font-mono font-black text-[#24251C] dark:text-[#EDE8D8] mt-0.5">
                    {data.exam.total_students}
                  </p>
                </div>
                <div className="text-center px-2 border-x border-[#E4DDCA]/60 dark:border-[#2C3022]">
                  <p className="text-[10px] uppercase font-bold text-emerald-700 dark:text-emerald-400">Present</p>
                  <p className="text-2xl font-mono font-black text-emerald-700 dark:text-emerald-400 mt-0.5">
                    {data.exam.present_count}
                  </p>
                </div>
                <div className="text-center px-2">
                  <p className="text-[10px] uppercase font-bold text-rose-600 dark:text-rose-400">Absentees</p>
                  <p className="text-2xl font-mono font-black text-rose-600 dark:text-rose-400 mt-0.5">
                    {data.exam.absent_count}
                  </p>
                </div>
              </div>
            </div>

            {/* Bottom Actions: [Download Form-B Absentees PDF], [Download Room Sign Sheets] */}
            <div className="mt-6 pt-4 border-t border-[#E4DDCA]/70 dark:border-[#2C3022] flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <span className="text-xs text-[#77735F] dark:text-[#A9AE8C]">
                Official Exam Documentation & Consolidated Attendance Registers:
              </span>

              <div className="flex items-center gap-2.5 flex-wrap">
                <button
                  type="button"
                  disabled={isDownloadingPdf}
                  onClick={handleDownloadFormBPdf}
                  className="inline-flex items-center gap-2 px-3.5 py-2 bg-[#6C5119] text-[#FBF8F0] text-xs font-bold rounded-xl hover:bg-[#584213] transition-all shadow-xs disabled:opacity-50 cursor-pointer"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  {isDownloadingPdf ? "Generating..." : "Download Form-B Absentees PDF"}
                </button>

                <button
                  type="button"
                  disabled={isDownloadingSheets}
                  onClick={handleDownloadRoomSheets}
                  className="inline-flex items-center gap-2 px-3.5 py-2 bg-[#F2EDE0] dark:bg-[#2C3117] text-[#24251C] dark:text-[#EDE8D8] text-xs font-bold rounded-xl border border-[#E4DDCA] dark:border-[#2C3022] hover:bg-[#EAE4D4] transition-all shadow-xs disabled:opacity-50 cursor-pointer"
                >
                  <svg className="w-4 h-4 text-[#3F451F] dark:text-[#D2A847]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  {isDownloadingSheets ? "Downloading..." : "Download Room Sign Sheets"}
                </button>
              </div>
            </div>
          </div>

          {/* Room-wise Summary Section */}
          <div className="space-y-3.5">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div>
                <h3 className="text-lg font-extrabold text-[#24251C] dark:text-[#EDE8D8]">
                  Room-wise Invigilation Progress
                </h3>
                <p className="text-xs text-[#77735F] dark:text-[#A9AE8C]">
                  Live status of room seating rosters and invigilator Form-B lock status.
                </p>
              </div>

              {/* Status Filter */}
              <div className="flex items-center gap-1.5 self-start sm:self-auto">
                {(["ALL", "OPEN", "SUBMITTED", "SCHEDULED"] as const).map((filter) => (
                  <button
                    key={filter}
                    onClick={() => setRoomFilter(filter)}
                    className={`px-3 py-1.5 rounded-xl text-xs font-bold tracking-wide transition-all cursor-pointer ${
                      roomFilter === filter
                        ? "bg-[#3F451F] text-[#FBF8F0]"
                        : "bg-[#FBF8F0] dark:bg-[#181913] text-[#77735F] dark:text-[#A9AE8C] border border-[#E4DDCA] dark:border-[#2C3022] hover:bg-[#EDE8D8]"
                    }`}
                  >
                    {filter === "ALL" ? "All Rooms" : filter}
                  </button>
                ))}
              </div>
            </div>

            {/* Grid of RoomCards */}
            {filteredRooms.length === 0 ? (
              <div className="bg-[#FBF8F0] dark:bg-[#181913] border border-[#E4DDCA] dark:border-[#2C3022] rounded-2xl p-8 text-center text-[#77735F]">
                <p className="text-xs font-semibold">No rooms match the selected filter.</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                {filteredRooms.map((room) => (
                  <RoomCard key={room.room_id} room={room} />
                ))}
              </div>
            )}
          </div>

          {/* Branch-wise Summary Section */}
          <div className="space-y-3.5">
            <div>
              <h3 className="text-lg font-extrabold text-[#24251C] dark:text-[#EDE8D8]">
                Branch-wise Consolidated Summary
              </h3>
              <p className="text-xs text-[#77735F] dark:text-[#A9AE8C]">
                Turnout ratio, candidate headcounts, and absentee rates grouped by engineering department.
              </p>
            </div>

            <BranchSummaryTable summaries={data.branch_summaries} />
          </div>
        </>
      )}

      {/* Modal: Create New Exam */}
      {isCreateOpen && (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-[#FBF8F0] dark:bg-[#181913] border border-[#E4DDCA] dark:border-[#2C3022] rounded-2xl p-6 max-w-lg w-full shadow-2xl animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between pb-3 border-b border-[#E4DDCA] dark:border-[#2C3022]">
              <h3 className="text-lg font-extrabold text-[#24251C] dark:text-[#EDE8D8]">
                Create New Examination
              </h3>
              <button
                type="button"
                onClick={() => setIsCreateOpen(false)}
                className="text-[#77735F] hover:text-[#24251C] p-1 rounded-lg"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCreateExamSubmit} className="mt-4 space-y-3.5">
              <div>
                <label className="block text-xs font-bold text-[#77735F] dark:text-[#A9AE8C] mb-1">
                  Exam Title
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. CIE-III November 2026"
                  value={createForm.title}
                  onChange={(e) => setCreateForm({ ...createForm, title: e.target.value })}
                  className="w-full bg-[#F2EDE0] dark:bg-[#11120D] border border-[#E4DDCA] dark:border-[#2C3022] rounded-xl px-3.5 py-2 text-sm text-[#24251C] dark:text-[#EDE8D8] focus:outline-none focus:border-[#3F451F]"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-[#77735F] dark:text-[#A9AE8C] mb-1">
                    Semester
                  </label>
                  <select
                    value={createForm.sem}
                    onChange={(e) => setCreateForm({ ...createForm, sem: e.target.value })}
                    className="w-full bg-[#F2EDE0] dark:bg-[#11120D] border border-[#E4DDCA] dark:border-[#2C3022] rounded-xl px-3 py-2 text-sm text-[#24251C] dark:text-[#EDE8D8] focus:outline-none focus:border-[#3F451F]"
                  >
                    {["Sem 1", "Sem 2", "Sem 3", "Sem 4", "Sem 5", "Sem 6", "Sem 7", "Sem 8"].map((s) => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-bold text-[#77735F] dark:text-[#A9AE8C] mb-1">
                    Primary Branch
                  </label>
                  <select
                    value={createForm.branch}
                    onChange={(e) => setCreateForm({ ...createForm, branch: e.target.value })}
                    className="w-full bg-[#F2EDE0] dark:bg-[#11120D] border border-[#E4DDCA] dark:border-[#2C3022] rounded-xl px-3 py-2 text-sm text-[#24251C] dark:text-[#EDE8D8] focus:outline-none focus:border-[#3F451F]"
                  >
                    {["CY", "CS", "IS", "EC", "EE", "ME", "CV", "AI"].map((b) => (
                      <option key={b} value={b}>{b}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-[#77735F] dark:text-[#A9AE8C] mb-1">
                    Course Code
                  </label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. 22CY72"
                    value={createForm.course_code}
                    onChange={(e) => setCreateForm({ ...createForm, course_code: e.target.value.toUpperCase() })}
                    className="w-full bg-[#F2EDE0] dark:bg-[#11120D] border border-[#E4DDCA] dark:border-[#2C3022] rounded-xl px-3.5 py-2 text-sm text-[#24251C] dark:text-[#EDE8D8] focus:outline-none focus:border-[#3F451F] font-mono"
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold text-[#77735F] dark:text-[#A9AE8C] mb-1">
                    Course Name (Optional)
                  </label>
                  <input
                    type="text"
                    placeholder="Cloud Security"
                    value={createForm.course_name}
                    onChange={(e) => setCreateForm({ ...createForm, course_name: e.target.value })}
                    className="w-full bg-[#F2EDE0] dark:bg-[#11120D] border border-[#E4DDCA] dark:border-[#2C3022] rounded-xl px-3.5 py-2 text-sm text-[#24251C] dark:text-[#EDE8D8] focus:outline-none focus:border-[#3F451F]"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-[#77735F] dark:text-[#A9AE8C] mb-1">
                    Examination Date
                  </label>
                  <input
                    type="date"
                    required
                    value={createForm.date}
                    onChange={(e) => setCreateForm({ ...createForm, date: e.target.value })}
                    className="w-full bg-[#F2EDE0] dark:bg-[#11120D] border border-[#E4DDCA] dark:border-[#2C3022] rounded-xl px-3.5 py-2 text-sm text-[#24251C] dark:text-[#EDE8D8] focus:outline-none focus:border-[#3F451F]"
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold text-[#77735F] dark:text-[#A9AE8C] mb-1">
                    Time Slot
                  </label>
                  <input
                    type="text"
                    required
                    placeholder="10:00-11:30 AM"
                    value={createForm.time}
                    onChange={(e) => setCreateForm({ ...createForm, time: e.target.value })}
                    className="w-full bg-[#F2EDE0] dark:bg-[#11120D] border border-[#E4DDCA] dark:border-[#2C3022] rounded-xl px-3.5 py-2 text-sm text-[#24251C] dark:text-[#EDE8D8] focus:outline-none focus:border-[#3F451F]"
                  />
                </div>
              </div>

              <div className="pt-3 flex items-center justify-end gap-2.5">
                <button
                  type="button"
                  onClick={() => setIsCreateOpen(false)}
                  className="px-4 py-2 rounded-xl text-xs font-bold text-[#77735F] hover:bg-[#F2EDE0] dark:hover:bg-[#2C3117] transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isCreating}
                  className="px-4 py-2 rounded-xl text-xs font-bold bg-[#3F451F] text-[#FBF8F0] hover:bg-[#323719] transition-colors disabled:opacity-50 cursor-pointer"
                >
                  {isCreating ? "Scheduling..." : "Confirm & Schedule"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Upload Seating CSV */}
      {isUploadOpen && (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-[#FBF8F0] dark:bg-[#181913] border border-[#E4DDCA] dark:border-[#2C3022] rounded-2xl p-6 max-w-md w-full shadow-2xl animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between pb-3 border-b border-[#E4DDCA] dark:border-[#2C3022]">
              <h3 className="text-lg font-extrabold text-[#24251C] dark:text-[#EDE8D8]">
                Upload Seating CSV
              </h3>
              <button
                type="button"
                onClick={() => setIsUploadOpen(false)}
                className="text-[#77735F] hover:text-[#24251C] p-1 rounded-lg"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleUploadSeatingSubmit} className="mt-4 space-y-4">
              <p className="text-xs text-[#77735F] dark:text-[#A9AE8C]">
                Upload student seating allocation matrix CSV file (columns: <code>Room, USN, Name, Branch, Seat</code>).
              </p>

              <div className="border-2 border-dashed border-[#E4DDCA] dark:border-[#2C3022] rounded-xl p-6 text-center hover:bg-[#F2EDE0]/50 transition-colors">
                <svg className="w-8 h-8 text-[#6C5119] dark:text-[#D2A847] mx-auto mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                </svg>
                <input
                  type="file"
                  accept=".csv,text/csv"
                  onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
                  className="block w-full text-xs text-[#77735F] file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-bold file:bg-[#3F451F] file:text-[#FBF8F0] hover:file:bg-[#323719] file:cursor-pointer cursor-pointer"
                />
                {selectedFile && (
                  <p className="mt-2 text-xs font-mono font-bold text-emerald-700 dark:text-emerald-400">
                    Selected: {selectedFile.name} ({(selectedFile.size / 1024).toFixed(1)} KB)
                  </p>
                )}
              </div>

              <div className="pt-2 flex items-center justify-end gap-2.5">
                <button
                  type="button"
                  onClick={() => setIsUploadOpen(false)}
                  className="px-4 py-2 rounded-xl text-xs font-bold text-[#77735F] hover:bg-[#F2EDE0] dark:hover:bg-[#2C3117] transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={!selectedFile || isUploading}
                  className="px-4 py-2 rounded-xl text-xs font-bold bg-[#3F451F] text-[#FBF8F0] hover:bg-[#323719] transition-colors disabled:opacity-50 cursor-pointer"
                >
                  {isUploading ? "Uploading & Allocating..." : "Process Seating CSV"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
