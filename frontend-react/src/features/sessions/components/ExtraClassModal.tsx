"use client";

import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createExtraSession, type ExtraSessionInput } from "@/services/api/sessions";
import { todayIso, ACADEMIC_DAY_START, ACADEMIC_DAY_END, validateAcademicWindow } from "@/lib/schedule";
import { useAuth } from "@/hooks/useAuth";

const DEPARTMENTS = [
  { id: "CSE-CY", name: "CSE (Cyber Security)" },
  { id: "CSE", name: "Computer Science & Engineering" },
  { id: "AIML", name: "Artificial Intelligence & ML" },
  { id: "ECE", name: "Electronics & Communication" },
  { id: "EEE", name: "Electrical & Electronics" },
  { id: "ME", name: "Mechanical Engineering" },
  { id: "CIVIL", name: "Civil Engineering" },
  { id: "ISE", name: "Information Science & Eng" },
];

const SEMESTERS = [1, 2, 3, 4, 5, 6, 7, 8];

const COMMON_ROOMS = [
  "CDS10-105",
  "LH-101",
  "LH-102",
  "LAB-1",
  "LAB-2",
  "LAB-3",
  "LH-201",
  "LH-202",
];

interface ExtraClassModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: () => void;
  initialSubjectCode?: string;
  initialDate?: string;
}

export function ExtraClassModal({
  isOpen,
  onClose,
  onSuccess,
  initialSubjectCode,
  initialDate,
}: ExtraClassModalProps) {
  const navigate = useNavigate();
  const { session } = useAuth();

  const userSubjects = session?.subjectCodes ?? [];
  const defaultSubj = initialSubjectCode || userSubjects[0] || "CN";

  const [subjectCode, setSubjectCode] = useState(defaultSubj);
  const [subjectName, setSubjectName] = useState("");
  const [date, setDate] = useState(initialDate || todayIso());
  const [startTime, setStartTime] = useState("14:00");
  const [endTime, setEndTime] = useState("15:00");
  const [roomId, setRoomId] = useState("CDS10-105");
  const [deptId, setDeptId] = useState("CSE-CY");
  const [semesterNumber, setSemesterNumber] = useState<number>(5);
  const [classType, setClassType] = useState<string>("EXTRA");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const check = validateAcademicWindow(startTime, endTime);
    if (!check.valid) {
      setError(check.message || "Class time is outside the academic window.");
      return;
    }

    if (!subjectCode.trim()) {
      setError("Please specify a subject code.");
      return;
    }

    if (!roomId.trim()) {
      setError("Please specify a classroom or lab.");
      return;
    }

    setIsSubmitting(true);
    try {
      const payload: ExtraSessionInput = {
        subject_code: subjectCode.trim().toUpperCase(),
        subject_name: subjectName.trim() || undefined,
        date,
        start_time: startTime,
        end_time: endTime,
        room_id: roomId.trim().toUpperCase(),
        dept_id: deptId,
        semester_number: semesterNumber,
        class_type: classType,
      };

      const result = await createExtraSession(payload);
      if (onSuccess) onSuccess();
      onClose();

      // Directly route teacher to take attendance for the created session
      navigate(`/attendance?session=${encodeURIComponent(result.session_id)}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create extra class.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-xs">
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl w-full max-w-lg shadow-xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="p-5 border-b border-[#E4DDCA] flex items-center justify-between bg-white">
          <div className="flex items-center space-x-2">
            <span className="p-2 rounded-xl bg-[#EDE8D8] text-base">⚡</span>
            <div>
              <h3 className="font-extrabold text-base text-[#24251C]">
                Schedule Extra / Emergency Class
              </h3>
              <p className="text-xs text-[#77735F]">
                Quickly create a class slot & auto-populate enrolled student roster
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            type="button"
            className="p-1 rounded-lg text-[#77735F] hover:bg-[#EDE8D8] transition-colors cursor-pointer"
          >
            ✕
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {error && (
            <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-800">
              {error}
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
            {/* Subject Code */}
            <div>
              <label className="block text-xs font-bold text-[#24251C] mb-1">
                Subject Code *
              </label>
              {userSubjects.length > 0 ? (
                <select
                  value={subjectCode}
                  onChange={(e) => setSubjectCode(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs font-bold text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
                >
                  {userSubjects.map((code) => (
                    <option key={code} value={code}>
                      {code}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type="text"
                  value={subjectCode}
                  onChange={(e) => setSubjectCode(e.target.value.toUpperCase())}
                  placeholder="e.g. CN, AI, SE"
                  className="w-full px-3 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
                  required
                />
              )}
            </div>

            {/* Course Title / Topic */}
            <div>
              <label className="block text-xs font-bold text-[#24251C] mb-1">
                Topic / Subject Name (Optional)
              </label>
              <input
                type="text"
                value={subjectName}
                onChange={(e) => setSubjectName(e.target.value)}
                placeholder="e.g. Computer Networks - Extra"
                className="w-full px-3 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
            {/* Class Type */}
            <div>
              <label className="block text-xs font-bold text-[#24251C] mb-1">
                Class Type
              </label>
              <select
                value={classType}
                onChange={(e) => setClassType(e.target.value)}
                className="w-full px-3 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
              >
                <option value="EXTRA">Extra Class</option>
                <option value="REMEDIAL">Remedial Class</option>
                <option value="EMERGENCY">Emergency Makeup</option>
                <option value="LAB">Makeup Lab</option>
              </select>
            </div>
          </div>

          {/* Department & Semester */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
            <div>
              <label className="block text-xs font-bold text-[#24251C] mb-1">
                Branch / Department *
              </label>
              <select
                value={deptId}
                onChange={(e) => setDeptId(e.target.value)}
                className="w-full px-3 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
              >
                {DEPARTMENTS.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-bold text-[#24251C] mb-1">
                Semester *
              </label>
              <select
                value={semesterNumber}
                onChange={(e) => setSemesterNumber(Number(e.target.value))}
                className="w-full px-3 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
              >
                {SEMESTERS.map((s) => (
                  <option key={s} value={s}>
                    Semester {s}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Date & Time Slot */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <label className="block text-xs font-bold text-[#24251C] mb-1">
                Date *
              </label>
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className="w-full px-3 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
                required
              />
            </div>

            <div>
              <label className="block text-xs font-bold text-[#24251C] mb-1">
                Start Time *
              </label>
              <input
                type="time"
                value={startTime}
                onChange={(e) => setStartTime(e.target.value)}
                min={ACADEMIC_DAY_START}
                max={ACADEMIC_DAY_END}
                className="w-full px-3 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
                required
              />
            </div>

            <div>
              <label className="block text-xs font-bold text-[#24251C] mb-1">
                End Time *
              </label>
              <input
                type="time"
                value={endTime}
                onChange={(e) => setEndTime(e.target.value)}
                min={ACADEMIC_DAY_START}
                max={ACADEMIC_DAY_END}
                className="w-full px-3 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
                required
              />
            </div>
          </div>

          {/* Room Selection */}
          <div>
            <label className="block text-xs font-bold text-[#24251C] mb-1">
              Classroom / Laboratory *
            </label>
            <div className="flex gap-2">
              <select
                value={roomId}
                onChange={(e) => setRoomId(e.target.value)}
                className="w-full px-3 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs font-bold text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
              >
                {COMMON_ROOMS.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Footer actions */}
          <div className="pt-3 border-t border-[#E4DDCA] flex items-center justify-end space-x-2">
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="px-4 py-2 rounded-xl text-xs font-bold text-[#77735F] hover:bg-[#EDE8D8] transition-colors cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-4 py-2 rounded-xl text-xs font-bold bg-[#6C5119] hover:bg-[#594214] text-white transition-colors cursor-pointer disabled:opacity-50 flex items-center space-x-1.5"
            >
              {isSubmitting ? (
                <>
                  <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  <span>Scheduling…</span>
                </>
              ) : (
                <>
                  <span>Create Class & Mark Attendance</span>
                  <span>→</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
