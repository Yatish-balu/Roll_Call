import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import {
  createTimetableEntry,
  fetchTimetableReference,
  fetchTimetableWeek,
  updateTimetableEntry,
  bulkAssignMasterTimetable,
  type TimetableEntry,
  type TimetableReference,
  type TimetableWeek,
  type MasterTimetableSlotInput,
} from "@/services/api/timetable";
import {
  ACADEMIC_DAY_END,
  ACADEMIC_DAY_START,
  durationMinutes,
  formatTimeWindow,
  todayIso,
  validateAcademicWindow,
} from "@/lib/schedule";
import { ExtraClassModal } from "@/features/sessions/components/ExtraClassModal";
import { DelegateClassModal } from "@/features/sessions/components/DelegateClassModal";
import { examsApi, type RoomAssignmentItem } from "@/services/api/exams";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

export interface StandardPeriod {
  period: number;
  label: string;
  start: string;
  end: string;
  isBreak?: boolean;
}

export const INSTITUTIONAL_PERIODS: StandardPeriod[] = [
  { period: 1, label: "Period 1", start: "09:00", end: "10:00" },
  { period: 2, label: "Period 2", start: "10:00", end: "11:00" },
  { period: 0, label: "Tea Break", start: "11:00", end: "11:15", isBreak: true },
  { period: 3, label: "Period 3", start: "11:15", end: "12:15" },
  { period: 4, label: "Period 4", start: "12:15", end: "13:15" },
  { period: 0, label: "Lunch Break", start: "13:15", end: "14:00", isBreak: true },
  { period: 5, label: "Period 5", start: "14:00", end: "15:00" },
  { period: 6, label: "Period 6", start: "15:00", end: "16:00" },
  { period: 7, label: "Period 7", start: "16:00", end: "17:00" },
];

function getEntriesForSlot(entries: TimetableEntry[], slot: StandardPeriod): TimetableEntry[] {
  if (slot.isBreak) return [];
  return entries.filter((entry) => {
    // Exact period match
    if (entry.period_number === slot.period) return true;
    // Exact time match
    if (entry.start_time === slot.start && entry.end_time === slot.end) return true;
    // 2-hour or multi-hour class spanning across this period (e.g. 14:00 - 16:00 covers slot 14:00-15:00 and 15:00-16:00)
    const eStart = entry.start_time;
    const eEnd = entry.end_time;
    if (eStart <= slot.start && eEnd >= slot.end) return true;
    return false;
  });
}

export function TimetableView() {
  const { session, canScheduleSessions, isAdmin } = useAuth();
  const today = todayIso();

  const [week, setWeek] = useState<TimetableWeek | null>(null);
  const [reference, setReference] = useState<TimetableReference | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedDay, setSelectedDay] = useState<string>("Monday");
  const [viewType, setViewType] = useState<"day" | "grid" | "invigilation">("day");
  const [viewScope, setViewScope] = useState<"my" | "dept">("my");
  const [isExtraModalOpen, setIsExtraModalOpen] = useState(false);
  const [invigilationDuties, setInvigilationDuties] = useState<RoomAssignmentItem[]>([]);
  const [isLoadingDuties, setIsLoadingDuties] = useState(false);
  const [dutiesError, setDutiesError] = useState<string | null>(null);

  const loadInvigilationDuties = useCallback(async () => {
    setIsLoadingDuties(true);
    setDutiesError(null);
    try {
      const myRooms = await examsApi.getMyAssignedRooms();
      setInvigilationDuties(myRooms);
    } catch (err: unknown) {
      setDutiesError(err instanceof Error ? err.message : "Failed to load invigilation duties.");
    } finally {
      setIsLoadingDuties(false);
    }
  }, []);

  useEffect(() => {
    void loadInvigilationDuties();
  }, [loadInvigilationDuties]);

  useEffect(() => {
    if (viewType === "invigilation") {
      void loadInvigilationDuties();
    }
  }, [viewType, loadInvigilationDuties]);
  const [delegatingEntry, setDelegatingEntry] = useState<{
    sessionId: string;
    subjectCode: string;
    subjectName: string;
    date: string;
    timeSlot: string;
  } | null>(null);

  // Master Timetable Upload (Admin only)
  const [isMasterModalOpen, setIsMasterModalOpen] = useState(false);
  const [masterJsonInput, setMasterJsonInput] = useState("");
  const [isSubmittingMaster, setIsSubmittingMaster] = useState(false);
  const [masterMessage, setMasterMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const handleLoadSampleTemplate = () => {
    const sample: MasterTimetableSlotInput[] = [
      { day: "Monday", start_time: "10:00", end_time: "11:00", subject_code: "CN", room_id: "LH-101", session_type: "THEORY" },
      { day: "Tuesday", start_time: "11:15", end_time: "12:15", subject_code: "DB-SYS", room_id: "LAB-1", session_type: "LAB" },
      { day: "Wednesday", start_time: "12:15", end_time: "13:15", subject_code: "AI", room_id: "LH-201", session_type: "THEORY" },
      { day: "Thursday", start_time: "09:00", end_time: "11:00", subject_code: "CN", room_id: "LAB-1", session_type: "LAB" },
      { day: "Friday", start_time: "11:15", end_time: "12:15", subject_code: "DB-SYS", room_id: "LH-102", session_type: "THEORY" },
      { day: "Saturday", start_time: "10:00", end_time: "11:00", subject_code: "AI", room_id: "CDS10-105", session_type: "THEORY" },
    ];
    setMasterJsonInput(JSON.stringify(sample, null, 2));
    setMasterMessage(null);
  };

  const handleSubmitMasterTimetable = async (e: React.FormEvent) => {
    e.preventDefault();
    setMasterMessage(null);
    let parsedSlots: MasterTimetableSlotInput[] = [];
    try {
      parsedSlots = JSON.parse(masterJsonInput);
      if (!Array.isArray(parsedSlots) || parsedSlots.length === 0) {
        throw new Error("Input must be a non-empty JSON array of timetable slots.");
      }
    } catch (err: unknown) {
      setMasterMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Invalid JSON format.",
      });
      return;
    }

    setIsSubmittingMaster(true);
    try {
      const res = await bulkAssignMasterTimetable(parsedSlots);
      setMasterMessage({
        type: "success",
        text: `Success! Distributed ${res.processed_slots} slot(s) to ${res.teachers_updated?.length || 0} faculty member(s) across subjects [${res.subjects_found?.join(", ")}].`,
      });
      void loadWeek();
    } catch (err: unknown) {
      setMasterMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Failed to assign master timetable slots.",
      });
    } finally {
      setIsSubmittingMaster(false);
    }
  };

  // Entry editor
  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const [editingEntry, setEditingEntry] = useState<TimetableEntry | null>(null);
  const [form, setForm] = useState({
    timetable_id: "",
    day_of_week: "Monday",
    period_number: 1,
    start_time: ACADEMIC_DAY_START,
    end_time: "10:00",
    subject_code: "",
    room_id: "",
    batch_id: "",
    faculty_id: "",
  });
  const [formError, setFormError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  const loadWeek = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchTimetableWeek({
        include_all: viewScope === "dept" || isAdmin,
      });
      setWeek(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "The timetable could not be loaded.");
    } finally {
      setIsLoading(false);
    }
  }, [viewScope, isAdmin]);

  useEffect(() => {
    void loadWeek();
    fetchTimetableReference()
      .then(setReference)
      .catch(() => setReference(null));
  }, [loadWeek]);

  const dayEntries = useMemo(() => {
    const day = week?.days.find((entry) => entry.day_of_week === selectedDay);
    return day?.entries ?? [];
  }, [week, selectedDay]);

  const entriesByDay = useMemo(() => {
    const map = new Map<string, TimetableEntry[]>();
    for (const day of week?.days ?? []) {
      map.set(day.day_of_week, day.entries);
    }
    return map;
  }, [week]);

  const gridSlots = INSTITUTIONAL_PERIODS;

  // Filter invigilation duties by current active week (Point 12)
  const currentWeekDuties = useMemo(() => {
    if (!invigilationDuties.length) return [];
    if (!week?.days || week.days.length === 0) return invigilationDuties;
    const weekDates = new Set(week.days.map((d) => d.date));
    return invigilationDuties.filter((duty) => duty.date && weekDates.has(duty.date));
  }, [invigilationDuties, week]);

  // Major events & upcoming duties beyond current week (Point 13 & 14)
  const nextWeekMajorEvents = useMemo(() => {
    const weekDates = new Set(week?.days?.map((d) => d.date) || []);
    const upcomingInvig = invigilationDuties
      .filter((duty) => duty.date && !weekDates.has(duty.date))
      .map((duty) => ({
        date: duty.date || "Next Week",
        title: `Exam Invigilation: ${duty.exam_name || duty.exam_id || "CIE"}`,
        subtitle: `Room ${duty.room_no} (${duty.start_time || "09:30"} - ${duty.end_time || "11:00"})`,
        tag: "Invigilation",
        tagColor: "bg-purple-100 text-purple-800 border-purple-200",
      }));

    // Curated major departmental upcoming events (Point 13)
    const staticEvents = [
      {
        date: "01/12/2026",
        title: "CIE-2 External Invigilation Duty",
        subtitle: "Room CDS 105 · Forenoon Session (09:30 - 11:00)",
        tag: "Invigilation",
        tagColor: "bg-purple-100 text-purple-800 border-purple-200",
      },
      {
        date: "03/12/2026",
        title: "5th Sem Student Presentations & Review",
        subtitle: "Lab CDS-101 · Cyber Security Evaluation (14:00 - 17:00)",
        tag: "5th Sem Review",
        tagColor: "bg-amber-100 text-amber-900 border-amber-200",
      },
      {
        date: "05/12/2026",
        title: "3rd Sem Make-Up / CIE Retest Exam",
        subtitle: "Classroom LH-201 · Marks & Verification",
        tag: "Make-Up Exam",
        tagColor: "bg-blue-100 text-blue-800 border-blue-200",
      },
    ];

    return upcomingInvig.length > 0 ? upcomingInvig : staticEvents;
  }, [invigilationDuties, week]);

  const openCreate = (day: string) => {
    setEditingEntry(null);
    setForm({
      timetable_id: reference?.timetables[0]?.timetable_id ?? "",
      day_of_week: day,
      period_number: 1,
      start_time: ACADEMIC_DAY_START,
      end_time: "10:00",
      subject_code: session?.subjectCodes?.[0] ?? "",
      room_id: reference?.rooms[0]?.room_id ?? "",
      batch_id: reference?.batches[0]?.batch_id ?? "",
      faculty_id: session?.userId ?? "",
    });
    setFormError(null);
    setIsEditorOpen(true);
  };

  const openEdit = (entry: TimetableEntry) => {
    setEditingEntry(entry);
    setForm({
      timetable_id: entry.timetable_id,
      day_of_week: entry.day_of_week,
      period_number: entry.period_number,
      start_time: entry.start_time,
      end_time: entry.end_time,
      subject_code: entry.subject_code,
      room_id: entry.room_id,
      batch_id: entry.batch_id ?? "",
      faculty_id: entry.faculty_id ?? "",
    });
    setFormError(null);
    setIsEditorOpen(true);
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setFormError(null);

    // Client-side policy check (the backend enforces the same rule).
    const windowCheck = validateAcademicWindow(form.start_time, form.end_time);
    if (!windowCheck.valid) {
      setFormError(windowCheck.message ?? "The class time is outside the academic day.");
      return;
    }
    if (!form.timetable_id) {
      setFormError("Select the timetable this class belongs to.");
      return;
    }
    if (!form.subject_code.trim()) {
      setFormError("A subject code is required.");
      return;
    }
    if (!form.room_id.trim()) {
      setFormError("A room is required.");
      return;
    }

    setIsSaving(true);
    try {
      const payload = {
        timetable_id: form.timetable_id,
        day_of_week: form.day_of_week,
        period_number: Number(form.period_number) || 1,
        start_time: form.start_time,
        end_time: form.end_time,
        subject_code: form.subject_code.trim().toUpperCase(),
        room_id: form.room_id.trim(),
        faculty_id: form.faculty_id.trim() || undefined,
        batch_id: form.batch_id.trim() || undefined,
      };
      if (editingEntry) {
        await updateTimetableEntry(editingEntry.entry_id, payload);
      } else {
        await createTimetableEntry(payload);
      }
      setIsEditorOpen(false);
      await loadWeek();
      window.dispatchEvent(new CustomEvent("rollcall:sessions-changed"));
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "The class could not be saved.");
    } finally {
      setIsSaving(false);
    }
  };

  const inputClass =
    "w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-sm text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]";
  const labelClass = "block text-xs font-bold text-[#24251C] mb-1";

  const todayWeekday = useMemo(() => {
    const names = [
      "Sunday",
      "Monday",
      "Tuesday",
      "Wednesday",
      "Thursday",
      "Friday",
      "Saturday",
    ];
    const parts = today.split("-");
    const date = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    return names[date.getDay()];
  }, [today]);

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5 flex-wrap">
            <h1 className="text-2xl sm:text-3xl font-extrabold text-[#24251C] tracking-tight">
              Timetable
            </h1>
            {session?.userId && (
              <span className="px-2.5 py-0.5 rounded-full text-[11px] font-black uppercase tracking-wider bg-[#3F451F] text-[#EDE8D8]">
                {session.userId}
              </span>
            )}
          </div>
          <p className="text-xs sm:text-sm text-[#77735F] mt-1">
            Weekly teaching schedule from the configured institutional timetable. Classes run
            strictly between {ACADEMIC_DAY_START} and {ACADEMIC_DAY_END}.
          </p>
        </div>

        <div className="flex items-center gap-2 self-start sm:self-auto flex-wrap">
          {/* My vs Department Switcher */}
          <div className="inline-flex rounded-xl border border-[#E4DDCA] bg-[#FBF8F0] p-1 shadow-2xs">
            <button
              type="button"
              onClick={() => setViewScope("my")}
              className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                viewScope === "my"
                  ? "bg-[#3F451F] text-[#EDE8D8]"
                  : "text-[#77735F] hover:text-[#24251C]"
              }`}
            >
              My Classes
            </button>
            <button
              type="button"
              onClick={() => setViewScope("dept")}
              className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                viewScope === "dept"
                  ? "bg-[#3F451F] text-[#EDE8D8]"
                  : "text-[#77735F] hover:text-[#24251C]"
              }`}
            >
              Department View
            </button>
          </div>

          {/* Day vs Grid vs Invigilation */}
          <div className="inline-flex rounded-xl border border-[#E4DDCA] bg-[#FBF8F0] p-1 shadow-2xs">
            {(["day", "grid", "invigilation"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => setViewType(mode)}
                className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer flex items-center gap-1.5 ${
                  viewType === mode
                    ? "bg-[#3F451F] text-[#EDE8D8]"
                    : "text-[#77735F] hover:text-[#24251C]"
                }`}
              >
                {mode === "day"
                  ? "Day View"
                  : mode === "grid"
                  ? "Weekly Grid"
                  : `📋 Invigilation Duties${invigilationDuties.length > 0 ? ` (${invigilationDuties.length})` : ""}`}
              </button>
            ))}
          </div>

          <button
            type="button"
            onClick={() => setViewType("invigilation")}
            className="px-3 py-2 rounded-xl border border-[#3F451F]/40 bg-[#EDE8D8] text-[#3F451F] text-xs font-bold hover:bg-[#E3DCB8] transition-colors cursor-pointer flex items-center gap-1.5 shadow-2xs"
            title="Check upcoming exam hall invigilation assignments"
          >
            <span>📝</span>
            <span>Check Invigilation Duties{invigilationDuties.length > 0 ? ` (${invigilationDuties.length})` : ""}</span>
          </button>

          <button
            type="button"
            onClick={() => setIsExtraModalOpen(true)}
            className="px-3 py-2 rounded-xl bg-[#6C5119] hover:bg-[#594214] text-white text-xs font-bold transition-colors cursor-pointer flex items-center space-x-1 shadow-2xs"
            title="Quickly schedule an extra or makeup class"
          >
            <span>➕</span>
            <span>Extra Class</span>
          </button>

          <button
            type="button"
            onClick={() => void loadWeek()}
            className="px-3 py-2 rounded-xl bg-[#FBF8F0] border border-[#E4DDCA] text-xs font-bold text-[#24251C] hover:bg-[#EDE8D8]/60 transition-colors cursor-pointer"
          >
            Refresh
          </button>

          {isAdmin && (
            <button
              type="button"
              onClick={() => {
                setMasterMessage(null);
                if (!masterJsonInput) handleLoadSampleTemplate();
                setIsMasterModalOpen(true);
              }}
              className="px-3 py-2 rounded-xl bg-[#3F451F] hover:bg-[#323719] text-[#EDE8D8] text-xs font-bold transition-colors cursor-pointer flex items-center space-x-1 shadow-2xs"
              title="Upload master institutional timetable to automatically distribute to all faculty"
            >
              <span>📅</span>
              <span>Master Timetable</span>
            </button>
          )}
          {canScheduleSessions && (
            <button
              type="button"
              onClick={() => openCreate(selectedDay)}
              disabled={!reference || reference.timetables.length === 0}
              className="px-3 py-2 rounded-xl bg-[#6C5119] text-white text-xs font-bold hover:bg-[#594214] transition-colors disabled:opacity-50 cursor-pointer"
              title={
                reference && reference.timetables.length === 0
                  ? "No timetable is configured on the server yet"
                  : "Add a class slot"
              }
            >
              Add class
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-800 flex items-center justify-between gap-3">
          <span>{error}</span>
          <button type="button" onClick={() => void loadWeek()} className="font-bold underline cursor-pointer">
            Retry
          </button>
        </div>
      )}

      {viewType === "invigilation" ? (
        <div className="space-y-5">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 bg-[#FBF8F0] p-4 rounded-2xl border border-[#E4DDCA]">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-lg">📋</span>
                <h2 className="text-base font-bold text-[#24251C]">
                  My Assigned Exam Invigilation Duties
                </h2>
                <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-[#3F451F] text-[#EDE8D8]">
                  {invigilationDuties.length} {invigilationDuties.length === 1 ? "Duty" : "Duties"}
                </span>
              </div>
              <p className="text-xs text-[#77735F] mt-0.5">
                Exam hall invigilation slots and Form-B attendance control. Click on any room to verify attendance and scan sheets.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => void loadInvigilationDuties()}
                disabled={isLoadingDuties}
                className="px-3 py-1.5 rounded-xl border border-[#E4DDCA] text-xs font-bold text-[#24251C] bg-white hover:bg-[#F2EDE0] transition-colors cursor-pointer flex items-center gap-1 shadow-2xs"
              >
                <span>🔄</span>
                <span>{isLoadingDuties ? "Refreshing..." : "Refresh"}</span>
              </button>
              <Link
                to="/exams"
                className="px-3 py-1.5 rounded-xl bg-[#3F451F] text-[#EDE8D8] text-xs font-bold hover:bg-[#343919] transition-colors shadow-2xs"
              >
                All Exams Module ➔
              </Link>
            </div>
          </div>

          {dutiesError && (
            <div className="p-4 rounded-xl bg-rose-50 border border-rose-200 text-xs font-medium text-rose-800">
              {dutiesError}
            </div>
          )}

          {isLoadingDuties ? (
            <div className="py-16 text-center text-xs text-[#77735F] bg-[#FBF8F0] rounded-2xl border border-[#E4DDCA]">
              <div className="w-6 h-6 border-2 border-[#6C5119] border-t-transparent rounded-full animate-spin mx-auto mb-2" />
              <span>Loading your invigilation assignments...</span>
            </div>
          ) : currentWeekDuties.length === 0 ? (
            <div className="py-16 text-center bg-[#FBF8F0] border border-dashed border-[#E4DDCA] rounded-2xl space-y-2">
              <span className="text-3xl">📝</span>
              <p className="font-bold text-[#24251C] text-sm">No Invigilation Duties for Current Week</p>
              <p className="text-xs text-[#77735F] max-w-md mx-auto px-4">
                You do not have any exam hall rooms assigned for invigilation during this active academic week. Check the upcoming events sidebar for duties scheduled in future weeks.
              </p>
              <div className="pt-2">
                <Link
                  to="/exams"
                  className="inline-flex items-center gap-1 text-xs font-bold text-[#6C5119] hover:underline"
                >
                  <span>Explore Scheduled Exams</span>
                  <span>➔</span>
                </Link>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {currentWeekDuties.map((duty) => {
                const statusColors = {
                  SCHEDULED: "bg-amber-100 text-amber-900 border-amber-300",
                  OPEN: "bg-emerald-100 text-emerald-900 border-emerald-300",
                  SUBMITTED: "bg-blue-100 text-blue-900 border-blue-300",
                  LATE_LOCKED: "bg-rose-100 text-rose-900 border-rose-300",
                };
                const statusPill =
                  statusColors[duty.status as keyof typeof statusColors] ||
                  "bg-gray-100 text-gray-800 border-gray-300";

                return (
                  <div
                    key={`${duty.exam_id}-${duty.room_no}`}
                    className="p-5 rounded-2xl border bg-[#FBF8F0] border-[#E4DDCA] hover:border-[#6C5119]/60 transition-all shadow-2xs flex flex-col justify-between space-y-4"
                  >
                    <div className="space-y-3">
                      <div className="flex items-center justify-between gap-2">
                        <span className="px-2.5 py-0.5 rounded-full text-[10px] font-black uppercase tracking-wider bg-[#EDE8D8] text-[#6C5119] border border-[#E4DDCA]">
                          {duty.subject_code || "EXAM"}
                        </span>
                        <span
                          className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider border ${statusPill}`}
                        >
                          {duty.status}
                        </span>
                      </div>

                      <div>
                        <h3 className="text-base font-extrabold text-[#24251C]">
                          Room {duty.display_room_no || duty.room_no}
                          {duty.block_name && ` · ${duty.block_name}`}
                        </h3>
                        <p className="text-xs font-semibold text-[#77735F] mt-0.5 truncate" title={duty.exam_name || duty.exam_id}>
                          {duty.exam_name || duty.exam_id}
                        </p>
                        {duty.subject_name && (
                          <p className="text-[11px] text-[#77735F] truncate">
                            {duty.subject_name}
                          </p>
                        )}
                      </div>

                      <div className="p-3 rounded-xl bg-white border border-[#E4DDCA] space-y-1.5 text-xs">
                        <div className="flex items-center justify-between">
                          <span className="text-[#77735F]">Date:</span>
                          <span className="font-bold text-[#24251C]">{duty.date || "Scheduled"}</span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-[#77735F]">Timing:</span>
                          <span className="font-bold text-[#24251C]">
                            {duty.start_time && duty.end_time
                              ? `${duty.start_time} - ${duty.end_time}`
                              : "Standard Slot"}
                          </span>
                        </div>
                        {duty.capacity && (
                          <div className="flex items-center justify-between">
                            <span className="text-[#77735F]">Capacity:</span>
                            <span className="font-medium text-[#24251C]">{duty.capacity} students</span>
                          </div>
                        )}
                      </div>
                    </div>

                    <div className="pt-2 border-t border-[#E4DDCA]/60 flex items-center justify-between gap-2">
                      <Link
                        to={`/exams/${duty.exam_id}/rooms/${duty.room_no}`}
                        className="flex-1 py-2 px-3 rounded-xl bg-[#3F451F] hover:bg-[#343919] text-[#EDE8D8] text-xs font-bold text-center transition-colors shadow-2xs flex items-center justify-center gap-1"
                      >
                        <span>Open Form-B</span>
                        <span>➔</span>
                      </Link>

                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      ) : isLoading ? (
        <div className="py-16 text-center text-[#77735F]">
          <div className="w-6 h-6 border-2 border-[#6C5119] border-t-transparent rounded-full animate-spin mx-auto mb-2" />
          <span>Loading the weekly schedule…</span>
        </div>
      ) : !week || !week.has_timetable ? (
        <div className="py-16 text-center bg-[#FBF8F0] border border-dashed border-[#E4DDCA] rounded-2xl">
          <p className="font-bold text-[#24251C]">No timetable is configured</p>
          <p className="text-xs text-[#77735F] mt-1 max-w-lg mx-auto px-4">
            {week?.message ||
              "The backend has no active timetable for your department yet. Once an administrator publishes a timetable, your weekly schedule appears here."}
          </p>
        </div>
      ) : week.total_entries === 0 ? (
        <div className="py-16 text-center bg-[#FBF8F0] border border-dashed border-[#E4DDCA] rounded-2xl">
          <p className="font-bold text-[#24251C]">Your timetable has no classes yet</p>
          <p className="text-xs text-[#77735F] mt-1 max-w-lg mx-auto px-4">
            {week.message ||
              "No timetable entries are visible for your account. Add a class slot to publish your teaching schedule."}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-4 gap-6 items-start">
          <div className="xl:col-span-3 space-y-5">
            {viewType === "day" ? (
              <div className="space-y-5">
                <div className="flex items-center gap-2 border-b border-[#E4DDCA] pb-3 overflow-x-auto">
                  {DAYS.map((day) => {
                    const count = entriesByDay.get(day)?.length ?? 0;
                    const isSelected = selectedDay === day;
                    const isToday = day === todayWeekday;
                    return (
                      <button
                        key={day}
                        type="button"
                        onClick={() => setSelectedDay(day)}
                        className={`px-4 py-2 rounded-xl text-xs sm:text-sm font-bold flex items-center space-x-2 transition-all cursor-pointer whitespace-nowrap ${
                          isSelected
                            ? "bg-[#6C5119] text-white shadow-sm"
                            : "bg-[#FBF8F0] border border-[#E4DDCA] text-[#77735F] hover:bg-[#EDE8D8]/50 hover:text-[#24251C]"
                        }`}
                      >
                        <span>{day}</span>
                        {isToday && (
                          <span className="px-1.5 py-0.2 rounded-full text-[9px] font-black bg-black/15 text-white">
                            Today
                          </span>
                        )}
                        <span
                          className={`px-1.5 py-0.2 rounded-full text-[10px] font-black ${
                            isSelected ? "bg-black/20 text-white" : "bg-[#EDE8D8] text-[#6C5119]"
                          }`}
                        >
                          {count}
                        </span>
                      </button>
                    );
                  })}
                </div>

                <div className="space-y-3.5">
                  <div className="flex items-center justify-between">
                    <h2 className="text-base font-bold text-[#24251C]">
                      {selectedDay} schedule ({dayEntries.length} class
                      {dayEntries.length === 1 ? "" : "es"})
                    </h2>
                    <span className="text-xs text-[#77735F] font-medium">
                      Academic day {ACADEMIC_DAY_START} - {ACADEMIC_DAY_END}
                    </span>
                  </div>

                  {dayEntries.length === 0 ? (
                    <div className="py-12 text-center bg-[#FBF8F0] border border-dashed border-[#E4DDCA] rounded-2xl">
                      <p className="text-sm font-bold text-[#24251C]">No classes on {selectedDay}</p>
                      <p className="text-xs text-[#77735F] mt-1">
                        The timetable has no slots for this weekday.
                      </p>
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 gap-3.5">
                      {dayEntries.map((entry) => (
                        <div
                          key={entry.entry_id}
                          className="p-5 rounded-2xl border bg-[#FBF8F0] border-[#E4DDCA] hover:border-[#6C5119]/60 transition-all shadow-2xs"
                        >
                          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                            <div className="flex items-center space-x-3.5">
                              <div className="p-3 rounded-xl flex flex-col items-center justify-center min-w-[78px] text-center border bg-[#6C5119]/10 border-[#6C5119]/20 text-[#6C5119]">
                                <span className="text-xs font-black tracking-wider uppercase">
                                  Period {entry.period_number}
                                </span>
                                <span className="text-[10px] font-bold mt-0.5">
                                  {durationMinutes(entry.start_time, entry.end_time)} MIN
                                </span>
                              </div>

                              <div className="space-y-1">
                                <div className="flex items-center space-x-2 flex-wrap">
                                  <span className="text-xs font-black px-2 py-0.5 rounded-md bg-[#EDE8D8] text-[#6C5119] border border-[#E4DDCA]">
                                    {entry.subject_code}
                                  </span>
                                  <span className="text-xs font-semibold text-[#77735F]">
                                    {formatTimeWindow(entry.start_time, entry.end_time)}
                                  </span>
                                </div>
                                <h3 className="text-base font-bold text-[#24251C]">
                                  {entry.subject_name || entry.subject_code}
                                </h3>
                                <div className="flex items-center gap-4 text-xs text-[#77735F] pt-1 flex-wrap">
                                  <span className="font-semibold text-[#24251C]">
                                    Room: {entry.room_name || entry.room_id}
                                  </span>
                                  {entry.batch_label && (
                                    <>
                                      <span>•</span>
                                      <span>Batch: {entry.batch_label}</span>
                                    </>
                                  )}
                                  {entry.faculty_id && (
                                    <>
                                      <span>•</span>
                                      <span>Faculty: {entry.faculty_name || entry.faculty_id}</span>
                                    </>
                                  )}
                                </div>
                              </div>
                            </div>

                            <div className="shrink-0 flex items-center gap-2 flex-wrap">
                              <Link
                                to={`/attendance?session=${encodeURIComponent(
                                  `AUTO-${today.replace(/-/g, "")}-${entry.subject_code}-${String(
                                    entry.period_number
                                  ).padStart(2, "0")}`
                                )}`}
                                className="px-3.5 py-2 rounded-xl bg-[#3F451F] text-[#EDE8D8] text-xs font-bold hover:bg-[#343919] transition-all shadow-2xs flex items-center space-x-1"
                              >
                                <span>🟢</span>
                                <span>Attendance</span>
                              </Link>
                              <button
                                type="button"
                                onClick={() =>
                                  setDelegatingEntry({
                                    sessionId: `AUTO-${today.replace(/-/g, "")}-${entry.subject_code}-${String(
                                      entry.period_number
                                    ).padStart(2, "0")}`,
                                    subjectCode: entry.subject_code,
                                    subjectName: entry.subject_name || entry.subject_code,
                                    date: today,
                                    timeSlot: `${entry.start_time} - ${entry.end_time}`,
                                  })
                                }
                                className="px-3 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs font-bold text-[#77735F] hover:text-[#24251C] hover:bg-[#EDE8D8]/60 transition-colors cursor-pointer flex items-center space-x-1"
                                title="Delegate this class to a colleague"
                              >
                                <span>🤝</span>
                                <span>Delegate</span>
                              </button>
                              {canScheduleSessions && (
                                <button
                                  type="button"
                                  onClick={() => openEdit(entry)}
                                  className="px-2.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs font-bold text-[#24251C] hover:bg-[#EDE8D8]/60 transition-colors cursor-pointer"
                                >
                                  Edit
                                </button>
                              )}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl shadow-2xs overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-left border-collapse min-w-[820px]">
                    <thead>
                      <tr className="bg-[#EDE8D8]/70 border-b border-[#E4DDCA] text-[#24251C]">
                        <th className="py-3.5 px-4 text-xs font-black uppercase tracking-wider w-40 border-r border-[#E4DDCA]">
                          Time
                        </th>
                        {DAYS.map((day) => (
                          <th
                            key={day}
                            className="py-3.5 px-4 text-xs font-black uppercase tracking-wider text-center border-r border-[#E4DDCA] last:border-r-0"
                          >
                            {day}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#E4DDCA] text-xs text-[#24251C]">
                      {gridSlots.map((slot) => {
                        if (slot.isBreak) {
                          return (
                            <tr key={slot.label} className="bg-amber-50/60 border-y border-amber-200/70">
                              <td className="py-2.5 px-4 font-bold border-r border-[#E4DDCA] bg-amber-100/50">
                                <span className="block text-xs font-black text-amber-900">
                                  ☕ {slot.label}
                                </span>
                                <span className="block text-[10px] text-amber-700 mt-0.5">
                                  {slot.start} - {slot.end}
                                </span>
                              </td>
                              <td
                                colSpan={DAYS.length}
                                className="py-2.5 px-4 text-center text-xs font-bold text-amber-900 tracking-wider uppercase bg-amber-50/40"
                              >
                                — {slot.label} Break ({slot.start} to {slot.end}) —
                              </td>
                            </tr>
                          );
                        }

                        return (
                          <tr key={`${slot.start}-${slot.end}`} className="hover:bg-[#EDE8D8]/20 transition-colors">
                            <td className="py-3 px-4 font-bold border-r border-[#E4DDCA] bg-[#EDE8D8]/15">
                              <span className="block text-xs font-black text-[#24251C]">
                                {slot.label}
                              </span>
                              <span className="block text-[10px] text-[#77735F] mt-0.5">
                                {slot.start} - {slot.end}
                              </span>
                            </td>
                            {DAYS.map((day) => {
                              const dayList = entriesByDay.get(day) || [];
                              const matchedEntries = getEntriesForSlot(dayList, slot);
                              return (
                                <td
                                  key={day}
                                  className="py-3 px-3 border-r border-[#E4DDCA] last:border-r-0 align-top"
                                >
                                  {matchedEntries.length > 0 ? (
                                    <div className="space-y-1.5">
                                      {matchedEntries.map((entry) => (
                                        <div
                                          key={entry.entry_id}
                                          className="p-2.5 rounded-xl border bg-[#EDE8D8]/40 border-[#E4DDCA] space-y-1"
                                        >
                                          <div className="flex items-center justify-between gap-1">
                                            <span className="font-black text-[10px] px-1.5 py-0.2 rounded bg-white text-[#3F451F]">
                                              {entry.subject_code}
                                            </span>
                                            {entry.start_time !== slot.start && (
                                              <span className="text-[9px] font-semibold text-purple-700 bg-purple-50 px-1 rounded">
                                                2-hr ({entry.start_time}-{entry.end_time})
                                              </span>
                                            )}
                                          </div>
                                          <p className="font-bold text-[#24251C] text-[11px] leading-tight line-clamp-2">
                                            {entry.subject_name || entry.subject_code}
                                          </p>
                                          <div className="text-[10px] text-[#77735F] flex items-center justify-between pt-0.5">
                                            <span className="font-semibold text-[#24251C]">
                                              {entry.room_name || entry.room_id}
                                            </span>
                                            {entry.batch_label && <span className="truncate">{entry.batch_label}</span>}
                                          </div>
                                        </div>
                                      ))}
                                    </div>
                                  ) : (
                                    <div className="h-full flex items-center justify-center py-4 text-[#77735F]/40 text-xs font-mono">
                                      —
                                    </div>
                                  )}
                                </td>
                              );
                            })}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>

          {/* Major Events & Duties Sidebar (Points 13 & 14) */}
          <div className="xl:col-span-1 space-y-4">
            <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-2xs space-y-3">
              <div className="flex items-center justify-between pb-2 border-b border-[#E4DDCA]">
                <div className="flex items-center gap-1.5">
                  <span className="text-base">📌</span>
                  <h3 className="text-xs font-black uppercase tracking-wider text-[#24251C]">
                    Upcoming Events
                  </h3>
                </div>
                <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-[#EDE8D8] text-[#6C5119]">
                  Next Week & Beyond
                </span>
              </div>
              <p className="text-[11px] text-[#77735F]">
                Institutional duties, invigilations, student presentations, and make-up exam slots for your classes.
              </p>

              <div className="space-y-2.5">
                {nextWeekMajorEvents.map((evt, idx) => (
                  <div
                    key={idx}
                    className="p-3 rounded-xl bg-white border border-[#E4DDCA] space-y-1 hover:border-[#6C5119]/50 transition-colors shadow-3xs"
                  >
                    <div className="flex items-center justify-between gap-1">
                      <span className="text-[10px] font-bold text-[#6C5119] flex items-center gap-1">
                        <span>🗓️</span>
                        <span>{evt.date}</span>
                      </span>
                      <span className={`text-[9px] font-black uppercase tracking-wider px-1.5 py-0.2 rounded border ${evt.tagColor}`}>
                        {evt.tag}
                      </span>
                    </div>
                    <p className="text-xs font-bold text-[#24251C] leading-snug">
                      {evt.title}
                    </p>
                    <p className="text-[10px] text-[#77735F] leading-tight">
                      {evt.subtitle}
                    </p>
                  </div>
                ))}
              </div>

              <div className="pt-2 border-t border-[#E4DDCA]/60 flex items-center justify-between">
                <Link
                  to="/exams"
                  className="text-[11px] font-bold text-[#3F451F] hover:underline flex items-center gap-1"
                >
                  <span>Exams Module</span>
                  <span>➔</span>
                </Link>
                <Link
                  to="/calendar"
                  className="text-[11px] font-bold text-[#6C5119] hover:underline flex items-center gap-1"
                >
                  <span>Full Calendar</span>
                  <span>➔</span>
                </Link>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Entry editor */}
      {isEditorOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-[2px] overflow-y-auto">
          <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-6 max-w-lg w-full shadow-xl space-y-4 my-8">
            <div className="flex items-center justify-between pb-2 border-b border-[#E4DDCA]">
              <h3 className="text-base font-bold text-[#24251C]">
                {editingEntry ? "Edit class slot" : "Add class slot"}
              </h3>
              <button
                type="button"
                onClick={() => setIsEditorOpen(false)}
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

            <form onSubmit={handleSubmit} className="space-y-4 text-sm">
              <div>
                <label className={labelClass} htmlFor="timetable">
                  Timetable *
                </label>
                <select
                  id="timetable"
                  className={`${inputClass} cursor-pointer`}
                  value={form.timetable_id}
                  onChange={(e) => setForm((prev) => ({ ...prev, timetable_id: e.target.value }))}
                  required
                >
                  <option value="">Select a timetable</option>
                  {(reference?.timetables ?? []).map((item) => (
                    <option key={item.timetable_id} value={item.timetable_id}>
                      {item.timetable_id} · {item.dept_id} / {item.semester_id} / {item.section_id}
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className={labelClass} htmlFor="day">
                    Weekday *
                  </label>
                  <select
                    id="day"
                    className={`${inputClass} cursor-pointer`}
                    value={form.day_of_week}
                    onChange={(e) => setForm((prev) => ({ ...prev, day_of_week: e.target.value }))}
                  >
                    {DAYS.map((day) => (
                      <option key={day} value={day}>
                        {day}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className={labelClass} htmlFor="period">
                    Period number *
                  </label>
                  <input
                    id="period"
                    type="number"
                    min={1}
                    max={12}
                    className={inputClass}
                    value={form.period_number}
                    onChange={(e) =>
                      setForm((prev) => ({ ...prev, period_number: Number(e.target.value) }))
                    }
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className={labelClass} htmlFor="startTime">
                    Start time *
                  </label>
                  <input
                    id="startTime"
                    type="time"
                    min={ACADEMIC_DAY_START}
                    max={ACADEMIC_DAY_END}
                    step={300}
                    className={inputClass}
                    value={form.start_time}
                    onChange={(e) => setForm((prev) => ({ ...prev, start_time: e.target.value }))}
                  />
                </div>
                <div>
                  <label className={labelClass} htmlFor="endTime">
                    End time *
                  </label>
                  <input
                    id="endTime"
                    type="time"
                    min={ACADEMIC_DAY_START}
                    max={ACADEMIC_DAY_END}
                    step={300}
                    className={inputClass}
                    value={form.end_time}
                    onChange={(e) => setForm((prev) => ({ ...prev, end_time: e.target.value }))}
                  />
                </div>
              </div>
              <p className="text-[11px] text-[#77735F]">
                Official classes run between {ACADEMIC_DAY_START} and {ACADEMIC_DAY_END}. The
                backend rejects any slot outside that window.
              </p>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className={labelClass} htmlFor="subjectCode">
                    Subject code *
                  </label>
                  <input
                    id="subjectCode"
                    className={`${inputClass} uppercase`}
                    value={form.subject_code}
                    onChange={(e) =>
                      setForm((prev) => ({ ...prev, subject_code: e.target.value.toUpperCase() }))
                    }
                    placeholder="e.g. NET-SEC"
                    required
                  />
                </div>
                <div>
                  <label className={labelClass} htmlFor="room">
                    Room *
                  </label>
                  <input
                    id="room"
                    list="room-options"
                    className={inputClass}
                    value={form.room_id}
                    onChange={(e) => setForm((prev) => ({ ...prev, room_id: e.target.value }))}
                    placeholder="e.g. LH-101"
                    required
                  />
                  <datalist id="room-options">
                    {(reference?.rooms ?? []).map((room) => (
                      <option key={room.room_id} value={room.room_id}>
                        {room.name}
                      </option>
                    ))}
                  </datalist>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className={labelClass} htmlFor="batch">
                    Batch
                  </label>
                  <input
                    id="batch"
                    list="batch-options"
                    className={inputClass}
                    value={form.batch_id}
                    onChange={(e) => setForm((prev) => ({ ...prev, batch_id: e.target.value }))}
                    placeholder="Optional"
                  />
                  <datalist id="batch-options">
                    {(reference?.batches ?? []).map((batch) => (
                      <option key={batch.batch_id} value={batch.batch_id}>
                        {batch.batch_label}
                      </option>
                    ))}
                  </datalist>
                </div>
                <div>
                  <label className={labelClass} htmlFor="faculty">
                    Faculty
                  </label>
                  <input
                    id="faculty"
                    className={inputClass}
                    value={form.faculty_id}
                    onChange={(e) => setForm((prev) => ({ ...prev, faculty_id: e.target.value }))}
                    placeholder={isAdmin ? "e.g. faculty_ml" : session?.userId ?? undefined}
                    readOnly={!isAdmin}
                  />
                </div>
              </div>

              <div className="pt-2 flex justify-end space-x-2">
                <button
                  type="button"
                  onClick={() => setIsEditorOpen(false)}
                  className="px-4 py-2 rounded-xl bg-[#EDE8D8] text-[#24251C] hover:bg-[#E4DDCA] font-semibold text-xs transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSaving}
                  className="px-4 py-2 rounded-xl bg-[#6C5119] hover:bg-[#594214] text-white font-bold text-xs transition-colors disabled:opacity-50 cursor-pointer"
                >
                  {isSaving ? "Saving…" : editingEntry ? "Save changes" : "Add class"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
      {/* Extra Class Modal */}
      <ExtraClassModal
        isOpen={isExtraModalOpen}
        onClose={() => setIsExtraModalOpen(false)}
        onSuccess={() => void loadWeek()}
      />

      {/* Class Delegation Modal */}
      {delegatingEntry && (
        <DelegateClassModal
          isOpen={Boolean(delegatingEntry)}
          onClose={() => setDelegatingEntry(null)}
          onSuccess={() => void loadWeek()}
          sessionId={delegatingEntry.sessionId}
          subjectCode={delegatingEntry.subjectCode}
          subjectName={delegatingEntry.subjectName}
          classDate={delegatingEntry.date}
          timeSlot={delegatingEntry.timeSlot}
        />
      )}
      {/* Master Timetable Ingestion Modal (Admin Only) */}
      {isMasterModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-xs animate-in fade-in duration-150">
          <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl max-w-2xl w-full p-6 shadow-2xl space-y-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-[#E4DDCA]">
              <div className="flex items-center space-x-2.5">
                <div className="w-8 h-8 rounded-xl bg-[#3F451F] text-white flex items-center justify-center font-bold text-sm">
                  📅
                </div>
                <div>
                  <h3 className="text-base font-bold text-[#24251C]">Master Institutional Timetable Ingestion</h3>
                  <p className="text-xs text-[#77735F]">Distribute weekly teaching schedules to all faculty at once</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setIsMasterModalOpen(false)}
                className="text-[#77735F] hover:text-[#24251C] text-sm font-bold cursor-pointer"
              >
                ✕
              </button>
            </div>

            {masterMessage && (
              <div
                className={`p-3 rounded-xl text-xs font-semibold ${
                  masterMessage.type === "success"
                    ? "bg-emerald-100 border border-emerald-300 text-emerald-900"
                    : "bg-rose-100 border border-rose-300 text-rose-900"
                }`}
              >
                {masterMessage.text}
              </div>
            )}

            <form onSubmit={handleSubmitMasterTimetable} className="space-y-4">
              <div className="flex items-center justify-between">
                <label className="block text-xs font-bold text-[#24251C]">
                  Timetable Slots JSON Array
                </label>
                <button
                  type="button"
                  onClick={handleLoadSampleTemplate}
                  className="text-xs font-bold text-[#6C5119] hover:underline cursor-pointer"
                >
                  Load Example Template
                </button>
              </div>

              <textarea
                required
                rows={12}
                value={masterJsonInput}
                onChange={(e) => setMasterJsonInput(e.target.value)}
                placeholder='[&#10;  { "day": "Monday", "start_time": "10:00", "end_time": "11:00", "subject_code": "CN", "room_id": "LH-101", "session_type": "THEORY" }&#10;]'
                className="w-full px-3.5 py-2.5 rounded-xl bg-white border border-[#E4DDCA] text-xs font-mono focus:outline-none focus:ring-2 focus:ring-[#6C5119]"
              />

              <div className="bg-[#EDE8D8]/50 p-3 rounded-xl border border-[#E4DDCA] text-xs text-[#77735F] space-y-1">
                <p className="font-bold text-[#24251C]">💡 How Institutional Propagation Works:</p>
                <p>
                  Each slot's <code className="text-[#6C5119] font-bold">subject_code</code> is matched against the institutional Faculty-Subject assignments. Every teacher assigned to that subject automatically receives the slot in their personal timetable grid and today's schedule!
                </p>
              </div>

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-[#E4DDCA]">
                <button
                  type="button"
                  onClick={() => setIsMasterModalOpen(false)}
                  className="px-4 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs font-bold text-[#77735F] hover:bg-[#EDE8D8]/50 cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingMaster || !masterJsonInput.trim()}
                  className="px-4 py-2 rounded-xl bg-[#3F451F] text-white text-xs font-bold hover:bg-[#323719] disabled:opacity-50 transition-all shadow-xs cursor-pointer"
                >
                  {isSubmittingMaster ? "Distributing Slots..." : "Propagate Master Timetable"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
