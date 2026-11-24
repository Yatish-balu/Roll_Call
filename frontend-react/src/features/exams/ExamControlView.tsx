"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  examsApi,
  type ExamItem,
  type RoomSummaryItem,
  type BranchSummaryItem,
  type MultiExamConsolidationResponse,
} from "@/services/api/exams";
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
          <div className="flex items-center gap-3">
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
                    Date: <strong>{selectedExam.date}</strong> · Time: <strong>{selectedExam.start_time} - {selectedExam.end_time}</strong> · Cutoff: <strong>{selectedExam.cutoff_minutes} mins</strong>
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
    </div>
  );
}
