import React, { useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import {
  createTimetableEntry,
  fetchTimetableReference,
  fetchTimetableWeek,
  updateTimetableEntry,
  type TimetableEntry,
  type TimetableReference,
  type TimetableWeek,
} from "@/services/api/timetable";
import { useResource } from "@/hooks/useResource";
import { invalidate } from "@/services/api/cache";

const TIMETABLE_WEEK_KEY = "/api/v1/timetable/week";
const TIMETABLE_REF_KEY = "/api/v1/timetable/reference";
import {
  ACADEMIC_DAY_END,
  ACADEMIC_DAY_START,
  durationMinutes,
  formatTimeWindow,
  todayIso,
  validateAcademicWindow,
} from "@/lib/schedule";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

export function TimetableView() {
  const { session, canScheduleSessions, isAdmin } = useAuth();
  const today = todayIso();

  const weekRes = useResource<TimetableWeek>(
    TIMETABLE_WEEK_KEY,
    () => fetchTimetableWeek()
  );
  const refRes = useResource<TimetableReference>(
    TIMETABLE_REF_KEY,
    () => fetchTimetableReference()
  );

  const week = weekRes.data ?? null;
  const reference = refRes.data ?? null;
  const isLoading = weekRes.isLoading && !weekRes.data;
  const error = weekRes.error
    ? weekRes.error instanceof Error
      ? weekRes.error.message
      : "The timetable could not be loaded."
    : null;

  const [selectedDay, setSelectedDay] = useState<string>("Monday");
  const [viewType, setViewType] = useState<"day" | "grid">("day");

  const loadWeek = useCallback(async () => {
    await weekRes.refresh();
  }, [weekRes]);

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

  const gridSlots = useMemo(() => {
    const times = new Map<string, { start: string; end: string; period: number }>();
    for (const entries of entriesByDay.values()) {
      for (const entry of entries) {
        const key = `${entry.start_time}-${entry.end_time}`;
        if (!times.has(key)) {
          times.set(key, {
            start: entry.start_time,
            end: entry.end_time,
            period: entry.period_number,
          });
        }
      }
    }
    return Array.from(times.values()).sort((a, b) => a.start.localeCompare(b.start));
  }, [entriesByDay]);

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
      invalidate([
        TIMETABLE_WEEK_KEY,
        TIMETABLE_REF_KEY,
        "/api/v1/sessions",
        "calendar",
        "dashboard",
      ]);
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

        <div className="flex items-center gap-2 self-start sm:self-auto">
          <div className="inline-flex rounded-xl border border-[#E4DDCA] bg-[#FBF8F0] p-1 shadow-2xs">
            {(["day", "grid"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => setViewType(mode)}
                className={`px-3.5 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                  viewType === mode
                    ? "bg-[#3F451F] text-[#EDE8D8]"
                    : "text-[#77735F] hover:text-[#24251C]"
                }`}
              >
                {mode === "day" ? "Day View" : "Weekly Grid"}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => void loadWeek()}
            className="px-3.5 py-2 rounded-xl bg-[#FBF8F0] border border-[#E4DDCA] text-xs font-bold text-[#24251C] hover:bg-[#EDE8D8]/60 transition-colors cursor-pointer"
          >
            Refresh
          </button>
          {canScheduleSessions && (
            <button
              type="button"
              onClick={() => openCreate(selectedDay)}
              disabled={!reference || reference.timetables.length === 0}
              className="px-3.5 py-2 rounded-xl bg-[#6C5119] text-white text-xs font-bold hover:bg-[#594214] transition-colors disabled:opacity-50 cursor-pointer"
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

      {isLoading ? (
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
      ) : viewType === "day" ? (
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

                      <div className="shrink-0 flex items-center gap-2">
                        <Link
                          to="/attendance"
                          className="px-4 py-2.5 rounded-xl bg-[#3F451F] text-[#EDE8D8] text-xs font-bold hover:bg-[#343919] transition-all shadow-2xs"
                        >
                          Take Attendance
                        </Link>
                        {canScheduleSessions && (
                          <button
                            type="button"
                            onClick={() => openEdit(entry)}
                            className="px-3 py-2.5 rounded-xl bg-white border border-[#E4DDCA] text-xs font-bold text-[#24251C] hover:bg-[#EDE8D8]/60 transition-colors cursor-pointer"
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
                {gridSlots.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="py-10 text-center text-[#77735F]">
                      No class slots are configured for this week.
                    </td>
                  </tr>
                ) : (
                  gridSlots.map((slot) => (
                    <tr key={`${slot.start}-${slot.end}`} className="hover:bg-[#EDE8D8]/20 transition-colors">
                      <td className="py-3 px-4 font-bold border-r border-[#E4DDCA] bg-[#EDE8D8]/15">
                        <span className="block text-xs font-black text-[#24251C]">
                          Period {slot.period}
                        </span>
                        <span className="block text-[10px] text-[#77735F] mt-0.5">
                          {slot.start} - {slot.end}
                        </span>
                      </td>
                      {DAYS.map((day) => {
                        const entry = (entriesByDay.get(day) || []).find(
                          (item) =>
                            item.start_time === slot.start && item.end_time === slot.end
                        );
                        return (
                          <td
                            key={day}
                            className="py-3 px-3 border-r border-[#E4DDCA] last:border-r-0 align-top"
                          >
                            {entry ? (
                              <div className="p-2.5 rounded-xl border bg-[#EDE8D8]/40 border-[#E4DDCA] space-y-1">
                                <div className="flex items-center justify-between gap-1">
                                  <span className="font-black text-[10px] px-1.5 py-0.2 rounded bg-white text-[#3F451F]">
                                    {entry.subject_code}
                                  </span>
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
                            ) : (
                              <div className="h-full flex items-center justify-center py-4 text-[#77735F]/40 text-xs font-mono">
                                —
                              </div>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))
                )}
              </tbody>
            </table>
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
    </div>
  );
}
