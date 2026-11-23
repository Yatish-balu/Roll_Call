"use client";

import React, { useEffect, useState, useCallback, useRef } from "react";
import { useParams } from "react-router-dom";
import {
  examsApi,
  type ExamSeatingItem,
  type RoomAssignmentItem,
} from "@/services/api/exams";
import { FormBTimer } from "./components/FormBTimer";

export function InvigilatorFormBView() {
  const { examId: routeExamId, roomNo: routeRoomNo } = useParams<{ examId?: string; roomNo?: string }>();

  const [assignedRooms, setAssignedRooms] = useState<RoomAssignmentItem[]>([]);
  const [selectedExamId, setSelectedExamId] = useState<string>(routeExamId || "");
  const [selectedRoomNo, setSelectedRoomNo] = useState<string>(routeRoomNo || "");
  const [currentRoom, setCurrentRoom] = useState<RoomAssignmentItem | null>(null);

  const [roster, setRoster] = useState<ExamSeatingItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isScanning, setIsScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notification, setNotification] = useState<string | null>(null);

  // Submit confirmation modal
  const [isSubmitModalOpen, setIsSubmitModalOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 1. Initial Load: get assigned rooms
  useEffect(() => {
    async function loadRooms() {
      try {
        setIsLoading(true);
        const myRooms = await examsApi.getMyAssignedRooms();
        setAssignedRooms(myRooms);

        if (!selectedExamId && !selectedRoomNo && myRooms.length > 0) {
          setSelectedExamId(myRooms[0].exam_id);
          setSelectedRoomNo(myRooms[0].room_no);
        } else if (routeExamId && routeRoomNo) {
          setSelectedExamId(routeExamId);
          setSelectedRoomNo(routeRoomNo);
        }
      } catch {
        // Fallback: if getMyAssignedRooms fails (e.g. admin or no assigned rooms), list exams
        try {
          const allExams = await examsApi.listExams();
          if (allExams.length > 0) {
            const firstExamId = allExams[0].exam_id;
            const rooms = await examsApi.listExamRooms(firstExamId);
            setAssignedRooms(rooms);
            if (rooms.length > 0) {
              setSelectedExamId(firstExamId);
              setSelectedRoomNo(rooms[0].room_no);
            }
          }
        } catch (innerErr) {
          setError(innerErr instanceof Error ? innerErr.message : "Failed to load invigilation rooms");
        }
      } finally {
        setIsLoading(false);
      }
    }
    loadRooms();
  }, [routeExamId, routeRoomNo, selectedExamId, selectedRoomNo]);

  // 2. Fetch roster and room assignment when selection changes
  const loadRoster = useCallback(async (examId: string, roomNo: string) => {
    if (!examId || !roomNo) return;
    try {
      setIsLoading(true);
      setError(null);
      const [assignment, students] = await Promise.all([
        examsApi.getRoomAssignment(examId, roomNo),
        examsApi.getRoomRoster(examId, roomNo),
      ]);
      setCurrentRoom(assignment);
      setRoster(students);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load room roster");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedExamId && selectedRoomNo) {
      loadRoster(selectedExamId, selectedRoomNo);
    }
  }, [selectedExamId, selectedRoomNo, loadRoster]);

  // Toggle student status (PRESENT <-> ABSENT)
  const toggleStudentStatus = (usn: string) => {
    if (currentRoom?.status === "SUBMITTED" || currentRoom?.status === "LATE_LOCKED") {
      alert("This room is locked. Attendance cannot be modified without Admin Override.");
      return;
    }
    setRoster((prev) =>
      prev.map((s) =>
        s.usn === usn
          ? {
              ...s,
              status: s.status === "PRESENT" ? "ABSENT" : "PRESENT",
              marked_source: "MANUAL",
            }
          : s
      )
    );
  };

  // Mark all present
  const markAllPresent = () => {
    if (currentRoom?.status === "SUBMITTED" || currentRoom?.status === "LATE_LOCKED") return;
    setRoster((prev) =>
      prev.map((s) => ({
        ...s,
        status: "PRESENT",
        marked_source: "MANUAL",
      }))
    );
  };

  // Save marks to backend
  const handleSaveMarks = async () => {
    if (!selectedExamId || !selectedRoomNo) return;
    try {
      setIsSaving(true);
      const marks = roster.map((s) => ({
        usn: s.usn,
        status: s.status,
      }));
      await examsApi.markRoomAttendance(selectedExamId, selectedRoomNo, {
        marks,
        marked_source: "MANUAL",
      });
      setNotification("Attendance marks saved successfully.");
      setTimeout(() => setNotification(null), 3000);
    } catch (err: unknown) {
      alert("Save failed: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setIsSaving(false);
    }
  };

  // Scan signed Form-B Photo (AI OCR Assist)
  const handlePhotoUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !selectedExamId || !selectedRoomNo) return;

    try {
      setIsScanning(true);
      setError(null);
      const res = await examsApi.scanFormBPhoto(selectedExamId, selectedRoomNo, file);

      // Merge AI scan results into roster
      if (res.extracted_rows && res.extracted_rows.length > 0) {
        const resultMap = new Map(res.extracted_rows.map((r) => [r.usn.toUpperCase(), r.status]));
        setRoster((prev) =>
          prev.map((s) => {
            const aiStatus = resultMap.get(s.usn.toUpperCase());
            if (aiStatus) {
              return { ...s, status: aiStatus, marked_source: "AI_SCAN" };
            }
            return s;
          })
        );
        setNotification(`AI Vision successfully matched ${res.matched_count} student signatures from Form-B.`);
      }
    } catch (err: unknown) {
      setError("AI Photo Scan failed: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setIsScanning(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  // Submit Form-B
  const handleConfirmSubmit = async () => {
    if (!selectedExamId || !selectedRoomNo) return;
    try {
      setIsSubmitting(true);
      // Save current marks first
      const marks = roster.map((s) => ({
        usn: s.usn,
        status: s.status,
      }));
      await examsApi.markRoomAttendance(selectedExamId, selectedRoomNo, {
        marks,
        marked_source: "MANUAL",
      });

      // Submit
      await examsApi.submitFormB(selectedExamId, selectedRoomNo);
      setIsSubmitModalOpen(false);
      setNotification("Form-B officially submitted to Exam Cell. Room is now locked.");
      // Reload room
      await loadRoster(selectedExamId, selectedRoomNo);
    } catch (err: unknown) {
      alert("Submission failed: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setIsSubmitting(false);
    }
  };

  // Download Blank Form-B Sign Sheet
  const handleDownloadPdf = async () => {
    if (!selectedExamId || !selectedRoomNo) return;
    try {
      const blob = await examsApi.downloadSignSheetPdf(selectedExamId, selectedRoomNo);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Form_B_SignSheet_${selectedExamId}_${selectedRoomNo}.pdf`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err: unknown) {
      alert("Download failed: " + (err instanceof Error ? err.message : String(err)));
    }
  };

  const presentCount = roster.filter((s) => s.status === "PRESENT").length;
  const absentCount = roster.filter((s) => s.status === "ABSENT").length;
  const isLocked = currentRoom?.status === "SUBMITTED" || currentRoom?.status === "LATE_LOCKED";

  return (
    <div className="space-y-6">
      {/* Top Banner & Room Switcher */}
      <div className="bg-white p-5 rounded-2xl border border-gray-200/80 shadow-sm flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xl">📝</span>
            <h2 className="text-xl font-bold text-gray-900">
              Invigilator Form-B Attendance Sheet
            </h2>
          </div>
          <p className="text-xs text-gray-500 mt-1">
            Mark student signatures, scan Form-B sheets using Google Gemini AI, and submit directly to Exam Cell.
          </p>
        </div>

        {/* Room Selector */}
        {assignedRooms.length > 1 && (
          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold text-gray-600">Switch Room:</label>
            <select
              value={`${selectedExamId}|${selectedRoomNo}`}
              onChange={(e) => {
                const [eId, rNo] = e.target.value.split("|");
                setSelectedExamId(eId);
                setSelectedRoomNo(rNo);
              }}
              className="rounded-xl border border-gray-300 p-2 text-sm bg-white font-medium text-gray-800"
            >
              {assignedRooms.map((r) => (
                <option key={`${r.exam_id}|${r.room_no}`} value={`${r.exam_id}|${r.room_no}`}>
                  {r.room_no} - {r.exam_name || r.exam_id}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {notification && (
        <div className="p-4 rounded-xl bg-emerald-50 border border-emerald-200 text-sm text-emerald-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span>✅</span>
            <span>{notification}</span>
          </div>
          <button onClick={() => setNotification(null)} className="text-emerald-900 font-bold">✕</button>
        </div>
      )}

      {error && (
        <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Room & Exam Information + Countdown Timer */}
      {currentRoom && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 bg-[#EDE8D8]/35 border border-[#3F451F]/15 rounded-2xl p-5">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-bold uppercase tracking-wider text-[#3F451F]">
                Exam Hall Assignment
              </span>
              <span className="text-xs px-2.5 py-0.5 rounded-full font-semibold bg-[#3F451F] text-white">
                {currentRoom.status}
              </span>
            </div>
            <h3 className="text-xl font-extrabold text-gray-900">
              Room {currentRoom.display_room_no || currentRoom.room_no}
              {currentRoom.block_name && ` · ${currentRoom.block_name}`}
            </h3>
            <p className="text-xs text-gray-600 mt-1">
              Exam: <strong>{currentRoom.exam_name || currentRoom.exam_id}</strong> · Subject: <strong>{currentRoom.subject_code}</strong> {currentRoom.subject_name && `(${currentRoom.subject_name})`}
            </p>
            <p className="text-xs text-gray-500 mt-1">
              Date: <strong>{currentRoom.date}</strong> · Schedule: <strong>{currentRoom.start_time} - {currentRoom.end_time}</strong> · Invigilator: <strong>{currentRoom.invigilator_id || "You"}</strong>
            </p>
          </div>

          <div>
            <FormBTimer
              cutoffAt={currentRoom.cutoff_at}
              status={currentRoom.status}
              onExpire={() => loadRoster(selectedExamId, selectedRoomNo)}
            />
          </div>
        </div>
      )}

      {/* Actions Toolbar */}
      <div className="bg-white p-4 rounded-2xl border border-gray-200/80 shadow-sm flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {/* AI Photo Scan Button */}
          <input
            type="file"
            ref={fileInputRef}
            onChange={handlePhotoUpload}
            accept="image/*"
            className="hidden"
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={isLocked || isScanning}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-purple-700 text-white text-xs font-semibold shadow hover:bg-purple-800 disabled:opacity-50 transition-colors"
          >
            <span>📸</span>
            {isScanning ? "Analyzing Signatures with AI..." : "Scan Form-B Sheet (AI Assist)"}
          </button>

          <button
            onClick={markAllPresent}
            disabled={isLocked}
            className="px-3 py-2 rounded-xl border border-gray-300 text-gray-700 text-xs font-medium hover:bg-gray-50 disabled:opacity-50"
          >
            Mark All Present
          </button>

          <button
            onClick={handleDownloadPdf}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl border border-gray-300 text-gray-700 text-xs font-medium hover:bg-gray-50"
          >
            <span>📄</span> Blank Form-B PDF
          </button>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleSaveMarks}
            disabled={isLocked || isSaving}
            className="px-4 py-2 rounded-xl bg-gray-900 text-white text-xs font-semibold hover:bg-black disabled:opacity-50 transition-colors"
          >
            {isSaving ? "Saving..." : "Save Draft"}
          </button>

          <button
            onClick={() => setIsSubmitModalOpen(true)}
            disabled={isLocked}
            className="px-4 py-2 rounded-xl bg-[#3F451F] text-white text-xs font-bold shadow hover:bg-[#343919] disabled:opacity-50 transition-colors"
          >
            🔒 Submit Form-B
          </button>
        </div>
      </div>

      {/* Stats Counter Bar */}
      <div className="grid grid-cols-3 gap-3 text-center">
        <div className="bg-white p-3.5 rounded-xl border">
          <span className="text-xs text-gray-500 font-medium">Total Registered</span>
          <p className="text-xl font-extrabold text-gray-900">{roster.length}</p>
        </div>
        <div className="bg-emerald-50/60 p-3.5 rounded-xl border border-emerald-100">
          <span className="text-xs text-emerald-700 font-medium">Present Candidates</span>
          <p className="text-xl font-extrabold text-emerald-800">{presentCount}</p>
        </div>
        <div className="bg-red-50/60 p-3.5 rounded-xl border border-red-100">
          <span className="text-xs text-red-600 font-medium">Absentees</span>
          <p className="text-xl font-extrabold text-red-700">{absentCount}</p>
        </div>
      </div>

      {/* Student Roster Table */}
      <div className="bg-white rounded-2xl border border-gray-200/80 shadow-sm overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
          <h3 className="text-sm font-bold text-gray-900">
            Form-B Seating Roster & Signatures
          </h3>
          <span className="text-xs text-gray-500">
            Click status button to toggle Present / Absent
          </span>
        </div>

        {isLoading ? (
          <div className="text-center py-12 text-sm text-gray-500">Loading student seating...</div>
        ) : roster.length === 0 ? (
          <div className="text-center py-12 text-sm text-gray-500">
            No seating records found for this room.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-100 text-sm">
              <thead className="bg-[#EDE8D8]/40">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-[#3F451F]">Sl No</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-[#3F451F]">USN</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-[#3F451F]">Student Name</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-[#3F451F]">Branch</th>
                  <th className="px-4 py-3 text-center text-xs font-semibold text-[#3F451F]">Desk / Seat</th>
                  <th className="px-4 py-3 text-center text-xs font-semibold text-[#3F451F]">Marked By</th>
                  <th className="px-4 py-3 text-right text-xs font-semibold text-[#3F451F]">Attendance Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {roster.map((student) => {
                  const isPresent = student.status === "PRESENT";
                  return (
                    <tr
                      key={student.usn}
                      className={`hover:bg-gray-50/70 transition-colors ${
                        !isPresent ? "bg-red-50/30" : ""
                      }`}
                    >
                      <td className="px-4 py-3 font-mono text-xs text-gray-500">{student.sl_no}</td>
                      <td className="px-4 py-3 font-mono font-bold text-gray-900">{student.usn}</td>
                      <td className="px-4 py-3 font-medium text-gray-800">{student.name}</td>
                      <td className="px-4 py-3 text-gray-600">
                        <span className="px-2 py-0.5 rounded text-xs bg-gray-100 font-mono">
                          {student.branch}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-center font-mono text-xs text-gray-700">
                        {student.seat_no || "—"}
                      </td>
                      <td className="px-4 py-3 text-center">
                        {student.marked_source === "AI_SCAN" ? (
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-purple-100 text-purple-800">
                            ✨ AI Vision
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 rounded-full text-[10px] text-gray-500 bg-gray-100">
                            Manual
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          type="button"
                          onClick={() => toggleStudentStatus(student.usn)}
                          disabled={isLocked}
                          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold transition-all shadow-sm ${
                            isPresent
                              ? "bg-emerald-600 text-white hover:bg-emerald-700"
                              : "bg-red-600 text-white hover:bg-red-700"
                          } disabled:opacity-70`}
                        >
                          <span>{isPresent ? "✓" : "✗"}</span>
                          <span>{isPresent ? "PRESENT" : "ABSENT"}</span>
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Submit Confirmation Dialog */}
      {isSubmitModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-xl border border-gray-200">
            <h4 className="text-lg font-bold text-gray-900 mb-2">
              Official Form-B Submission
            </h4>
            <p className="text-xs text-gray-600 mb-4">
              You are about to officially submit the Form-B attendance for Room <strong>{selectedRoomNo}</strong> to the Exam Cell. Once submitted:
            </p>

            <div className="bg-gray-50 rounded-xl p-3 space-y-1.5 text-xs text-gray-700 mb-4">
              <div className="flex justify-between">
                <span>Total Candidates:</span>
                <span className="font-bold">{roster.length}</span>
              </div>
              <div className="flex justify-between text-emerald-700">
                <span>Present Candidates:</span>
                <span className="font-bold">{presentCount}</span>
              </div>
              <div className="flex justify-between text-red-600">
                <span>Absentees:</span>
                <span className="font-bold">{absentCount}</span>
              </div>
            </div>

            <p className="text-[11px] text-amber-800 bg-amber-50 p-2.5 rounded-xl border border-amber-200 mb-4">
              ⚠️ <strong>Final Warning:</strong> This submission is final and cryptographically logged. Further modifications require Chief Superintendent Admin Override.
            </p>

            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setIsSubmitModalOpen(false)}
                className="px-4 py-2 rounded-xl text-xs font-medium text-gray-600 hover:bg-gray-100"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmSubmit}
                disabled={isSubmitting}
                className="px-4 py-2 rounded-xl text-xs font-bold bg-[#3F451F] text-white hover:bg-[#343919]"
              >
                {isSubmitting ? "Submitting..." : "Yes, Submit Form-B"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
