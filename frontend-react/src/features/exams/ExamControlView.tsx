"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  examsApi,
  type ExamItem,
  type ExamType,
  type RoomSummaryItem,
  type BranchSummaryItem,
  type MultiExamConsolidationResponse,
} from "@/services/api/exams";
import { apiClient } from "@/services/api/client";
import { useAuth } from "@/hooks/useAuth";
import { RoomCard } from "./components/RoomCard";
import { BranchSummaryTable } from "./components/BranchSummaryTable";
import { BranchConsolidationMatrix } from "./components/BranchConsolidationMatrix";

export function ExamControlView() {
  const navigate = useNavigate();
  const { isAdmin } = useAuth();

  const [activeTab, setActiveTab] = useState<"rooms" | "consolidation">("rooms");
  const [exams, setExams] = useState<ExamItem[]>([]);
  const [selectedExamId, setSelectedExamId] = useState<string>("");
  const [selectedExam, setSelectedExam] = useState<ExamItem | null>(null);

  const [rooms, setRooms] = useState<RoomSummaryItem[]>([]);
  const [branches, setBranches] = useState<BranchSummaryItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Multi-exam CIE Branch Consolidation state
  const [consolidationData, setConsolidationData] = useState<MultiExamConsolidationResponse | null>(null);
  const [isLoadingConsolidation, setIsLoadingConsolidation] = useState(false);

  // Admin Override Modal state
  const [overrideRoomNo, setOverrideRoomNo] = useState<string | null>(null);
  const [overrideReason, setOverrideReason] = useState("");
  const [overrideStatus, setOverrideStatus] = useState<"OPEN" | "SUBMITTED">("OPEN");
  const [isSubmittingOverride, setIsSubmittingOverride] = useState(false);
  const [overrideMsg, setOverrideMsg] = useState<string | null>(null);

  // Admin Invigilator Assignment Modal state
  const [assignModalRoomNo, setAssignModalRoomNo] = useState<string | null>(null);
  const [selectedTeacherId, setSelectedTeacherId] = useState<string>("");
  const [isAssigning, setIsAssigning] = useState(false);
  const [candidates, setCandidates] = useState<Array<{
    user_id: string;
    name: string;
    has_timetable_conflict: boolean;
    conflict_details?: string;
    is_already_assigned: boolean;
    assigned_room?: string;
    is_recommended: boolean;
    priority: number;
  }>>([]);
  const [isLoadingCandidates, setIsLoadingCandidates] = useState(false);

  const DEFAULT_FACULTY = [
    { id: "pallavi", name: "Dr. Pallavi Kulkarni (CY)" },
    { id: "mangala", name: "Mangala L (CY)" },
    { id: "shankar", name: "Dr. Shankar Gowda (CY)" },
    { id: "test_faculty", name: "Prof. Faculty (Faculty Demo)" },
  ];

  // Fetch candidates with live timetable conflict analysis
  useEffect(() => {
    async function loadCandidates() {
      if (!selectedExamId || !assignModalRoomNo) return;
      setIsLoadingCandidates(true);
      try {
        const list = await examsApi.getInvigilatorCandidates(selectedExamId);
        setCandidates(list);
        const rec = list.find((c) => c.is_recommended);
        if (rec) {
          setSelectedTeacherId(rec.user_id);
        } else if (list.length > 0) {
          setSelectedTeacherId(list[0].user_id);
        }
      } catch (e) {
        console.warn("Could not load invigilator candidates with conflicts", e);
      } finally {
        setIsLoadingCandidates(false);
      }
    }
    loadCandidates();
  }, [selectedExamId, assignModalRoomNo]);

  // Admin Exam Sitting Creation Modal State (Points: Semester, CIE, Mid, Lab, SEE)
  const [isCreateExamOpen, setIsCreateExamOpen] = useState(false);
  const [createExamType, setCreateExamType] = useState<ExamType>("THEORY_CIE");
  const [createSemester, setCreateSemester] = useState<number>(5);
  const [createDept, setCreateDept] = useState("CY");
  const [createSubjectCode, setCreateSubjectCode] = useState("22CY52");
  const [createSubjectName, setCreateSubjectName] = useState("Computer Networks");
  const [createExamName, setCreateExamName] = useState("5th Sem CIE-2 Cyber Security");
  const [createDate, setCreateDate] = useState(() => new Date().toISOString().split("T")[0]);
  const [createStartTime, setCreateStartTime] = useState("09:30");
  const [createEndTime, setCreateEndTime] = useState("11:00");
  const [createRooms, setCreateRooms] = useState("CDS-105, CDS-106");
  const [isSubmittingCreate, setIsSubmittingCreate] = useState(false);

  // Standard Department Subjects reference
  const DEPARTMENT_SUBJECTS: Record<number, Array<{ code: string; name: string }>> = {
    3: [
      { code: "22CY31", name: "Data Structures & Applications" },
      { code: "22CY32", name: "Digital Design & Computer Organization" },
      { code: "22CY33", name: "Operating Systems Principles" },
    ],
    5: [
      { code: "22CY51", name: "Software Engineering & Architecture" },
      { code: "22CY52", name: "Computer Networks & Protocols" },
      { code: "22CY53", name: "Database Systems & Administration" },
      { code: "22CY54", name: "Theory of Computation" },
    ],
    7: [
      { code: "22CY71", name: "Applied Cryptography & Network Security" },
      { code: "22CY72", name: "Cloud Infrastructure & Application Security" },
      { code: "22HS71A", name: "Constitution of India, Ethics & Cyber Law" },
    ],
  };

  const handleSemesterChange = (sem: number) => {
    setCreateSemester(sem);
    const subs = DEPARTMENT_SUBJECTS[sem];
    if (subs && subs.length > 0) {
      setCreateSubjectCode(subs[0].code);
      setCreateSubjectName(subs[0].name);
      setCreateExamName(`${sem}th Sem ${getExamTypeLabel(createExamType)} ${subs[0].code}`);
    } else {
      setCreateExamName(`${sem}th Sem ${getExamTypeLabel(createExamType)} Examination`);
    }
  };

  const getExamTypeLabel = (type: ExamType) => {
    switch (type) {
      case "THEORY_CIE": return "Internal Assessment (CIE)";
      case "MID_TERM": return "Mid-Term Examination";
      case "LAB_CIE": return "Laboratory Practical CIE";
      case "THEORY_SEE": return "Semester End Exam (SEE Theory)";
      case "LAB_EXTERNAL": return "SEE Lab Practical Exam";
      default: return "Examination";
    }
  };

  const handleCreateExamSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!createExamName.trim() || !createSubjectCode.trim() || !createDate) {
      alert("Please fill all required exam details.");
      return;
    }
    const cleanExamId = `EXAM-${createDate.replace(/-/g, "")}-${createSubjectCode.replace(/[^A-Za-z0-9]/g, "")}-${createExamType.slice(0, 3)}`;
    const parsedRooms = createRooms
      .split(/[,;\s]+/)
      .map((r) => r.trim().toUpperCase())
      .filter(Boolean);

    try {
      setIsSubmittingCreate(true);
      const newExam = await examsApi.createExam({
        exam_id: cleanExamId,
        name: createExamName.trim(),
        exam_type: createExamType,
        semester: Number(createSemester),
        department: createDept.trim().toUpperCase(),
        date: createDate,
        start_time: createStartTime,
        end_time: createEndTime,
        cutoff_minutes: 0, // Demo mode: cutoff disabled
        subject_code: createSubjectCode.trim().toUpperCase(),
        subject_name: createSubjectName.trim(),
        rooms: parsedRooms,
      });

      setOverrideMsg(
        `Exam Sitting '${newExam.name}' (${newExam.exam_id}) created successfully with Form-B attendance sheets for rooms: ${parsedRooms.join(", ") || "No rooms specified"}.`
      );
      setIsCreateExamOpen(false);
      await loadExams();
      setSelectedExamId(newExam.exam_id);
    } catch (err: unknown) {
      alert("Failed to schedule exam: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setIsSubmittingCreate(false);
    }
  };

  // Handle Invigilator Assignment
  const handleAssignSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedExamId || !assignModalRoomNo || !selectedTeacherId) {
      alert("Please select a faculty invigilator to assign to this exam room.");
      return;
    }
    try {
      setIsAssigning(true);
      await examsApi.assignRoomInvigilator(selectedExamId, assignModalRoomNo, {
        invigilator_id: selectedTeacherId,
      });
      const teacherName =
        candidates.find((c) => c.user_id === selectedTeacherId)?.name ||
        DEFAULT_FACULTY.find((f) => f.id === selectedTeacherId)?.name ||
        selectedTeacherId;
      setOverrideMsg(`Successfully assigned ${teacherName} to Room ${assignModalRoomNo} for exam ${selectedExamId}.`);
      setAssignModalRoomNo(null);
      await loadSummaries(selectedExamId);
    } catch (err: unknown) {
      alert("Assignment failed: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setIsAssigning(false);
    }
  };

  // Load initial exams
  const loadExams = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const list = await examsApi.listExams();
      setExams(list);
      if (list.length > 0 && !selectedExamId) {
        setSelectedExamId(list[0].exam_id);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load exams");
    } finally {
      setIsLoading(false);
    }
  }, [selectedExamId]);

  useEffect(() => {
    loadExams();
  }, [loadExams]);

  // Load summaries when exam changes
  const loadSummaries = useCallback(async (examId: string) => {
    if (!examId) return;
    try {
      setIsLoading(true);
      setError(null);
      const [roomData, branchData] = await Promise.all([
        examsApi.getRoomWiseSummary(examId),
        examsApi.getBranchWiseSummary(examId),
      ]);
      setRooms(roomData);
      setBranches(branchData);
      const cur = exams.find((e) => e.exam_id === examId) || null;
      setSelectedExam(cur);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load exam summaries");
    } finally {
      setIsLoading(false);
    }
  }, [exams]);

  useEffect(() => {
    if (selectedExamId) {
      loadSummaries(selectedExamId);
    }
  }, [selectedExamId, loadSummaries]);

  // Load multi-exam branch consolidation
  const loadConsolidation = useCallback(async (sem: number = 7) => {
    try {
      setIsLoadingConsolidation(true);
      const data = await examsApi.getBranchConsolidation({ semester: sem });
      setConsolidationData(data);
    } catch (err: unknown) {
      console.error("Failed to load consolidation data:", err);
    } finally {
      setIsLoadingConsolidation(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === "consolidation" && !consolidationData) {
      loadConsolidation(7);
    }
  }, [activeTab, consolidationData, loadConsolidation]);

  // Download Absentees PDF
  const handleDownloadAbsentees = async () => {
    if (!selectedExamId) return;
    try {
      const blob = await examsApi.downloadAbsenteesPdf(selectedExamId);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Form_B_Absentees_${selectedExamId}.pdf`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err: unknown) {
      alert("Failed to download absentees PDF: " + (err instanceof Error ? err.message : String(err)));
    }
  };


  // Admin Override Submit
  const handleOverrideSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedExamId || !overrideRoomNo || !overrideReason.trim()) {
      alert("Please provide a valid reason for this override (mandatory for audit trail)");
      return;
    }
    try {
      setIsSubmittingOverride(true);
      const res = await examsApi.adminOverrideRoom(selectedExamId, overrideRoomNo, {
        reason: overrideReason.trim(),
        new_status: overrideStatus,
      });
      setOverrideMsg(`Room ${overrideRoomNo} status updated to ${res.room_status}`);
      setOverrideRoomNo(null);
      setOverrideReason("");
      // Reload room summaries
      await loadSummaries(selectedExamId);
    } catch (err: unknown) {
      alert("Override failed: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setIsSubmittingOverride(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 bg-white p-5 rounded-2xl border border-gray-200/80 shadow-sm">
        <div>
          <h2 className="text-xl font-bold text-gray-900 flex items-center gap-2">
            <span>📋</span> Exam Cell — Form-B Control Center
          </h2>
          <p className="text-xs text-gray-500 mt-1">
            Real-time VTU/DSCE Form-B exam hall attendance, room tracking, and automated absentee reports.
          </p>
        </div>

        {activeTab === "rooms" && (
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2">
              <label htmlFor="exam-select" className="text-xs font-semibold text-gray-600">Select Exam:</label>
              <select
                id="exam-select"
                value={selectedExamId}
                onChange={(e) => setSelectedExamId(e.target.value)}
                className="rounded-xl border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-800 shadow-sm focus:border-[#3F451F] focus:outline-none"
              >
                {exams.map((ex) => (
                  <option key={ex.exam_id} value={ex.exam_id}>
                    {ex.name} ({ex.exam_id})
                  </option>
                ))}
              </select>
            </div>

            {isAdmin && (
              <button
                type="button"
                onClick={() => setIsCreateExamOpen(true)}
                className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-[#3F451F] text-white text-xs font-semibold shadow hover:bg-[#343919] transition-colors whitespace-nowrap"
              >
                <span>➕</span> Schedule Exam Sitting
              </button>
            )}
          </div>
        )}
      </div>

      {/* View Switcher Tabs */}
      <div className="flex gap-2 border-b border-gray-200 pb-1">
        <button
          onClick={() => setActiveTab("rooms")}
          className={`px-5 py-2.5 text-sm font-semibold rounded-xl transition-all flex items-center gap-2 ${
            activeTab === "rooms"
              ? "bg-[#3F451F] text-white shadow"
              : "bg-white text-gray-600 hover:text-gray-900 border border-gray-200"
          }`}
        >
          <span>🏢</span> Exam Hall & Rooms Status
        </button>
        <button
          onClick={() => setActiveTab("consolidation")}
          className={`px-5 py-2.5 text-sm font-semibold rounded-xl transition-all flex items-center gap-2 ${
            activeTab === "consolidation"
              ? "bg-[#3F451F] text-white shadow"
              : "bg-white text-gray-600 hover:text-gray-900 border border-gray-200"
          }`}
        >
          <span>📊</span> Multi-Exam Branch Matrix (CIE Consolidation)
        </button>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-sm text-red-700">
          {error}
        </div>
      )}

      {overrideMsg && (
        <div className="p-4 rounded-xl bg-emerald-50 border border-emerald-200 text-sm text-emerald-800 flex items-center justify-between">
          <span>{overrideMsg}</span>
          <button onClick={() => setOverrideMsg(null)} className="text-emerald-900 font-bold">✕</button>
        </div>
      )}

      {activeTab === "consolidation" ? (
        <BranchConsolidationMatrix
          branches={consolidationData?.branches || []}
          seriesTitle={consolidationData?.series_title}
          semester={consolidationData?.semester || 7}
          isLoading={isLoadingConsolidation}
        />
      ) : (
        <>
          {/* Selected Exam Active Banner */}
          {selectedExam && (
            <div className="bg-[#EDE8D8]/40 border border-[#3F451F]/15 rounded-2xl p-5">
              <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-[#3F451F] text-white">
                      {selectedExam.exam_type}
                    </span>
                    <span className="text-xs font-medium text-gray-600">
                      Subject: <strong className="text-gray-900">{selectedExam.subject_code}</strong> {selectedExam.subject_name && `(${selectedExam.subject_name})`}
                    </span>
                  </div>
                  <h3 className="text-lg font-bold text-gray-900 mt-1">{selectedExam.name}</h3>
                  <p className="text-xs text-gray-600">
                    Date: <strong>{selectedExam.date}</strong> · Time: <strong>{selectedExam.start_time} - {selectedExam.end_time}</strong> · Cutoff: <strong>{selectedExam.cutoff_minutes === 0 ? "No lock (demo)" : `${selectedExam.cutoff_minutes} mins`}</strong>
                  </p>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <button
                    onClick={handleDownloadAbsentees}
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-[#3F451F] text-white text-xs font-semibold shadow hover:bg-[#343919] transition-colors"
                  >
                    <span>📑</span> Download Form-B Absentees PDF
                  </button>
                  <button
                    onClick={() => navigate("/invigilation")}
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-white border border-gray-300 text-gray-800 text-xs font-semibold hover:bg-gray-50 transition-colors"
                  >
                    <span>📝</span> Open Invigilator View
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Room Summary Grid */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-base font-bold text-gray-900">Room-Wise Attendance Status</h3>
              <span className="text-xs text-gray-500">{rooms.length} Exam Rooms</span>
            </div>

            {isLoading ? (
              <div className="text-center py-12 text-sm text-gray-500">Loading room attendance data...</div>
            ) : rooms.length === 0 ? (
              <div className="bg-white p-8 rounded-2xl border text-center text-gray-500 text-sm">
                No rooms registered for this exam yet.
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                {rooms.map((room) => (
                  <RoomCard
                    key={room.room_no}
                    room={room}
                    examId={selectedExamId}
                    isAdmin={isAdmin}
                    onSelect={(roomNo) => navigate(`/exams/${selectedExamId}/rooms/${encodeURIComponent(roomNo)}`)}
                    onAdminOverride={(roomNo) => setOverrideRoomNo(roomNo)}
                    onAssignInvigilator={(roomNo) => {
                      setAssignModalRoomNo(roomNo);
                    }}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Branch Summary */}
          <div className="bg-white rounded-2xl border border-gray-200/80 p-5 shadow-sm">
            <h3 className="text-base font-bold text-gray-900 mb-3">Branch-Wise Consolidation</h3>
            <BranchSummaryTable branches={branches} />
          </div>
        </>
      )}

      {/* Admin Override Modal */}
      {overrideRoomNo && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-xl border border-gray-200">
            <h4 className="text-lg font-bold text-gray-900 mb-1">
              Admin Override: Room {overrideRoomNo}
            </h4>
            <p className="text-xs text-gray-500 mb-4">
              Unlocking or modifying a room after cutoff requires an official audit reason stored in the immutable HMAC audit trail.
            </p>

            <form onSubmit={handleOverrideSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">
                  New Status
                </label>
                <select
                  value={overrideStatus}
                  onChange={(e) => setOverrideStatus(e.target.value as "OPEN" | "SUBMITTED")}
                  className="w-full rounded-xl border border-gray-300 p-2 text-sm"
                >
                  <option value="OPEN">OPEN (Allow Invigilator to edit & submit)</option>
                  <option value="SUBMITTED">SUBMITTED (Force marked as submitted)</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">
                  Reason for Override <span className="text-red-500">*</span>
                </label>
                <textarea
                  required
                  rows={3}
                  value={overrideReason}
                  onChange={(e) => setOverrideReason(e.target.value)}
                  placeholder="e.g. Chief Superintendent permitted late entry due to verified transit delay..."
                  className="w-full rounded-xl border border-gray-300 p-2 text-sm focus:border-[#3F451F] focus:outline-none"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setOverrideRoomNo(null)}
                  className="px-4 py-2 rounded-xl text-xs font-medium text-gray-600 hover:bg-gray-100"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingOverride}
                  className="px-4 py-2 rounded-xl text-xs font-semibold bg-[#3F451F] text-white hover:bg-[#343919]"
                >
                  {isSubmittingOverride ? "Applying..." : "Confirm Override"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Admin Invigilator Assignment Modal with Timetable Conflict Detection */}
      {assignModalRoomNo && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-xl border border-gray-200">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xl">👤</span>
              <h4 className="text-lg font-bold text-gray-900">
                Assign Invigilator: Room {assignModalRoomNo}
              </h4>
            </div>
            <p className="text-xs text-gray-500 mb-4">
              Allocate an active faculty member to invigilate exam <strong>{selectedExamId}</strong> in room <strong>{assignModalRoomNo}</strong>. The system checks the institutional timetable to prevent double-booking teaching faculty.
            </p>

            <form onSubmit={handleAssignSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">
                  Select Faculty Teacher <span className="text-red-500">*</span>
                </label>
                {isLoadingCandidates ? (
                  <div className="p-3 text-xs text-gray-500 bg-gray-50 rounded-xl border border-gray-200">
                    Checking timetable schedules & faculty availability...
                  </div>
                ) : (
                  <select
                    required
                    value={selectedTeacherId}
                    onChange={(e) => setSelectedTeacherId(e.target.value)}
                    className="w-full rounded-xl border border-gray-300 bg-white p-2.5 text-sm font-medium text-gray-800 shadow-xs focus:border-[#3F451F] focus:outline-none"
                  >
                    <option value="" disabled>-- Select a faculty member --</option>
                    {candidates.length > 0 ? (
                      <>
                        <optgroup label="🟢 Available Faculty (No Timetable Conflict)">
                          {candidates
                            .filter((c) => !c.has_timetable_conflict && !c.is_already_assigned)
                            .map((c) => (
                              <option key={c.user_id} value={c.user_id}>
                                {c.name} — ✅ Available & Free
                              </option>
                            ))}
                        </optgroup>
                        <optgroup label="⚠️ Class Conflict (Busy Teaching Timetable Period)">
                          {candidates
                            .filter((c) => c.has_timetable_conflict && !c.is_already_assigned)
                            .map((c) => (
                              <option key={c.user_id} value={c.user_id}>
                                {c.name} — ⚠️ {c.conflict_details || "Teaching Class"}
                              </option>
                            ))}
                        </optgroup>
                        <optgroup label="🔒 Already Assigned to Another Room">
                          {candidates
                            .filter((c) => c.is_already_assigned)
                            .map((c) => (
                              <option key={c.user_id} value={c.user_id}>
                                {c.name} — 🔒 Assigned to Room {c.assigned_room}
                              </option>
                            ))}
                        </optgroup>
                      </>
                    ) : (
                      DEFAULT_FACULTY.map((f) => (
                        <option key={f.id} value={f.id}>
                          {f.name}
                        </option>
                      ))
                    )}
                  </select>
                )}
              </div>

              {/* Conflict Analysis Banner */}
              {(() => {
                const candidate = candidates.find((c) => c.user_id === selectedTeacherId);
                if (!candidate) return null;
                if (candidate.has_timetable_conflict) {
                  return (
                    <div className="p-3 bg-amber-50 border border-amber-300 rounded-xl text-xs text-amber-900 flex items-start gap-2">
                      <span className="text-base">⚠️</span>
                      <div>
                        <strong className="block font-semibold">Timetable Conflict Detected:</strong>
                        <span>{candidate.name} is scheduled to teach during this exam period: <strong>{candidate.conflict_details}</strong>.</span>
                        <p className="mt-1 text-amber-800">
                          To avoid missing regular lectures, consider selecting an available faculty member from the green recommended list above.
                        </p>
                      </div>
                    </div>
                  );
                }
                if (candidate.is_already_assigned) {
                  return (
                    <div className="p-3 bg-red-50 border border-red-200 rounded-xl text-xs text-red-800 flex items-center gap-2">
                      <span>🔒</span>
                      <span><strong>{candidate.name}</strong> is already assigned to invigilate <strong>Room {candidate.assigned_room}</strong> for this exam sitting.</span>
                    </div>
                  );
                }
                return (
                  <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-xl text-xs text-emerald-900 flex items-center gap-2">
                    <span>✅</span>
                    <span><strong>{candidate.name}</strong> has no timetable teaching conflicts and is fully available.</span>
                  </div>
                );
              })()}

              <div className="p-3 bg-blue-50/70 border border-blue-200/60 rounded-xl text-xs text-blue-900">
                💡 <strong>Auto-Sync:</strong> Once assigned, this room will instantly synchronize to the teacher&apos;s &ldquo;My Invigilation&rdquo; dashboard with official VTU/DSCE Form-B digital rosters.
              </div>

              <div className="flex items-center justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setAssignModalRoomNo(null)}
                  className="px-4 py-2 rounded-xl text-xs font-medium text-gray-600 hover:bg-gray-100"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isAssigning}
                  className="px-4 py-2 rounded-xl text-xs font-bold bg-[#3F451F] text-white hover:bg-[#343919]"
                >
                  {isAssigning ? "Assigning..." : "Confirm Assignment"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Admin Exam Sitting Creation Modal (All Semesters, CIE, Mid-Term, Lab, SEE) */}
      {isCreateExamOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 overflow-y-auto">
          <div className="bg-white rounded-2xl max-w-xl w-full p-6 shadow-xl border border-gray-200 my-8">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className="text-xl">📅</span>
                <h4 className="text-lg font-bold text-gray-900">
                  Schedule College Exam Sitting
                </h4>
              </div>
              <button
                type="button"
                onClick={() => setIsCreateExamOpen(false)}
                className="text-gray-400 hover:text-gray-600 text-lg font-bold"
              >
                ✕
              </button>
            </div>
            <p className="text-xs text-gray-500 mb-5">
              Create an institutional examination across any Semester (1st-8th), Category (CIE Internal, Mid-Term, Lab CIE, SEE Theory, SEE Lab), and Subject with auto-generated Form-B attendance rosters.
            </p>

            <form onSubmit={handleCreateExamSubmit} className="space-y-4">
              {/* Exam Category */}
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1.5">
                  Exam Type / Category <span className="text-red-500">*</span>
                </label>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  {[
                    { id: "THEORY_CIE", label: "CIE Internal", icon: "📝" },
                    { id: "MID_TERM", label: "Mid-Term Exam", icon: "📑" },
                    { id: "LAB_CIE", label: "Lab Practical CIE", icon: "🔬" },
                    { id: "THEORY_SEE", label: "SEE Theory", icon: "🏛️" },
                    { id: "LAB_EXTERNAL", label: "SEE Lab Exam", icon: "🧪" },
                  ].map((cat) => (
                    <button
                      key={cat.id}
                      type="button"
                      onClick={() => {
                        setCreateExamType(cat.id as ExamType);
                        setCreateExamName(`${createSemester}th Sem ${getExamTypeLabel(cat.id as ExamType)} ${createSubjectCode}`);
                      }}
                      className={`p-2.5 rounded-xl border text-left text-xs font-semibold flex items-center gap-2 transition-all ${
                        createExamType === cat.id
                          ? "border-[#3F451F] bg-[#3F451F]/10 text-[#3F451F] ring-1 ring-[#3F451F]"
                          : "border-gray-200 text-gray-700 hover:bg-gray-50"
                      }`}
                    >
                      <span>{cat.icon}</span>
                      <span>{cat.label}</span>
                    </button>
                  ))}
                </div>
              </div>

              {/* Semester & Department */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1">
                    Semester <span className="text-red-500">*</span>
                  </label>
                  <select
                    value={createSemester}
                    onChange={(e) => handleSemesterChange(Number(e.target.value))}
                    className="w-full rounded-xl border border-gray-300 bg-white p-2.5 text-xs font-medium text-gray-800"
                  >
                    {[1, 2, 3, 4, 5, 6, 7, 8].map((sem) => (
                      <option key={sem} value={sem}>
                        {sem}th Semester
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1">
                    Department / Branch <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    required
                    value={createDept}
                    onChange={(e) => setCreateDept(e.target.value)}
                    placeholder="e.g. CY, CSE, ISE, ECE"
                    className="w-full rounded-xl border border-gray-300 p-2 text-xs uppercase font-medium"
                  />
                </div>
              </div>

              {/* Subject Code & Name */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1">
                    Subject Code <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    required
                    value={createSubjectCode}
                    onChange={(e) => {
                      setCreateSubjectCode(e.target.value);
                      setCreateExamName(`${createSemester}th Sem ${getExamTypeLabel(createExamType)} ${e.target.value}`);
                    }}
                    placeholder="e.g. 22CY52"
                    className="w-full rounded-xl border border-gray-300 p-2 text-xs uppercase font-bold"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1">
                    Subject Name
                  </label>
                  <input
                    type="text"
                    value={createSubjectName}
                    onChange={(e) => setCreateSubjectName(e.target.value)}
                    placeholder="e.g. Computer Networks & Protocols"
                    className="w-full rounded-xl border border-gray-300 p-2 text-xs"
                  />
                </div>
              </div>

              {/* Exam Title */}
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">
                  Exam Title / Sitting Name <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  required
                  value={createExamName}
                  onChange={(e) => setCreateExamName(e.target.value)}
                  className="w-full rounded-xl border border-gray-300 p-2 text-xs font-medium"
                />
              </div>

              {/* Date & Time */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1">
                    Exam Date <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="date"
                    required
                    value={createDate}
                    onChange={(e) => setCreateDate(e.target.value)}
                    className="w-full rounded-xl border border-gray-300 p-2 text-xs"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1">
                    Start Time <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="time"
                    required
                    value={createStartTime}
                    onChange={(e) => setCreateStartTime(e.target.value)}
                    className="w-full rounded-xl border border-gray-300 p-2 text-xs"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1">
                    End Time <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="time"
                    required
                    value={createEndTime}
                    onChange={(e) => setCreateEndTime(e.target.value)}
                    className="w-full rounded-xl border border-gray-300 p-2 text-xs"
                  />
                </div>
              </div>

              {/* Quick Time Presets */}
              <div className="flex items-center gap-2 text-xs text-gray-500">
                <span className="font-semibold text-gray-700">Quick Slots:</span>
                <button
                  type="button"
                  onClick={() => { setCreateStartTime("09:30"); setCreateEndTime("11:00"); }}
                  className="px-2 py-1 bg-gray-100 hover:bg-gray-200 rounded-lg text-xs font-medium text-gray-700"
                >
                  Forenoon (09:30 - 11:00)
                </button>
                <button
                  type="button"
                  onClick={() => { setCreateStartTime("14:00"); setCreateEndTime("15:30"); }}
                  className="px-2 py-1 bg-gray-100 hover:bg-gray-200 rounded-lg text-xs font-medium text-gray-700"
                >
                  Afternoon (14:00 - 15:30)
                </button>
                <button
                  type="button"
                  onClick={() => { setCreateStartTime("14:00"); setCreateEndTime("17:00"); }}
                  className="px-2 py-1 bg-gray-100 hover:bg-gray-200 rounded-lg text-xs font-medium text-gray-700"
                >
                  3-Hr SEE (14:00 - 17:00)
                </button>
              </div>

              {/* Exam Halls / Rooms */}
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">
                  Exam Halls / Rooms (Comma-separated) <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  required
                  value={createRooms}
                  onChange={(e) => setCreateRooms(e.target.value)}
                  placeholder="e.g. CDS-105, CDS-106, CDS-107"
                  className="w-full rounded-xl border border-gray-300 p-2 text-xs font-bold uppercase"
                />
                <span className="text-[11px] text-gray-500 mt-1 block">
                  Students enrolled in Semester {createSemester} ({createDept}) will be automatically allocated across these rooms with individual Form-B seating entries.
                </span>
              </div>

              <div className="p-3 bg-emerald-50/70 border border-emerald-200/60 rounded-xl text-xs text-emerald-900">
                📋 <strong>Automated Form-B Sync:</strong> Creating this exam will automatically generate VTU/DSCE Form-B attendance sheets for all specified rooms and register them for invigilator allocation.
              </div>

              <div className="flex items-center justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsCreateExamOpen(false)}
                  className="px-4 py-2 rounded-xl text-xs font-medium text-gray-600 hover:bg-gray-100"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingCreate}
                  className="px-5 py-2 rounded-xl text-xs font-bold bg-[#3F451F] text-white hover:bg-[#343919] shadow"
                >
                  {isSubmittingCreate ? "Scheduling..." : "Schedule Exam & Generate Form-B"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
