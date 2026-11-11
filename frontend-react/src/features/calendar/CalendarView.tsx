import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  loadMonthCalendarData,
  type CalendarDaySummary,
  type CalendarMonthData,
} from "@/services/api/calendar";
import {
  fetchSessionAllocations,
  fetchSessions,
  type SessionAllocation,
  type SessionItem,
} from "@/services/api/sessions";
import { useAuth } from "@/hooks/useAuth";
import { usePreference } from "@/lib/preferences";
import {
  addDaysIso,
  formatIsoDate,
  startOfWeekIso,
  todayIso,
  weekdayOfIsoDate,
} from "@/lib/schedule";

type CalendarViewMode = "month" | "week" | "day";

const WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const WEEKDAY_LABELS_MONDAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function CalendarView() {
  const { session } = useAuth();
  const [showHeatmap, setShowHeatmap] = usePreference("calendarShowHeatmap");
  const [weekStartsMonday, setWeekStartsMonday] = usePreference("calendarWeekStartsMonday");
  const [defaultView, setDefaultView] = usePreference("calendarDefaultView");

  const today = todayIso();
  const [viewMode, setViewMode] = useState<CalendarViewMode>(defaultView);
  const [anchorDate, setAnchorDate] = useState<string>(today);
  const [selectedDate, setSelectedDate] = useState<string>(today);

  const [monthData, setMonthData] = useState<CalendarMonthData | null>(null);
  const [weekSessions, setWeekSessions] = useState<SessionItem[]>([]);
  const [weekAllocations, setWeekAllocations] = useState<SessionAllocation[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSubject, setSelectedSubject] = useState("ALL");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const subjectOptions = useMemo(() => {
    const codes = new Set<string>();
    (session?.subjectCodes || []).forEach((code) => codes.add(code));
    return ["ALL", ...Array.from(codes)];
  }, [session?.subjectCodes]);

  const { year, month } = useMemo(() => {
    const parts = anchorDate.split("-");
    return { year: Number(parts[0]), month: Number(parts[1]) - 1 };
  }, [anchorDate]);

  /* ------------------------------------------------------------------ */
  /* Loading                                                             */
  /* ------------------------------------------------------------------ */

  const loadMonth = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await loadMonthCalendarData(year, month, selectedSubject, today);
      setMonthData(data);
      setLastUpdated(new Date());
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "The calendar could not be loaded.");
    } finally {
      setIsLoading(false);
    }
  }, [year, month, selectedSubject, today]);

  const loadWeek = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const weekStart = startOfWeekIso(anchorDate);
      const weekEnd = addDaysIso(weekStart, 6);
      const [sessionsRes, allocationsRes] = await Promise.all([
        fetchSessions({ limit: 200, from_date: weekStart, to_date: weekEnd }),
        fetchSessionAllocations({ from_date: weekStart, to_date: weekEnd }),
      ]);
      setWeekSessions(sessionsRes.items || []);
      setWeekAllocations(allocationsRes.items || []);
      setLastUpdated(new Date());
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "The week could not be loaded.");
    } finally {
      setIsLoading(false);
    }
  }, [anchorDate]);

  const loadDay = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [sessionsRes, allocationsRes] = await Promise.all([
        fetchSessions({ limit: 50, date: anchorDate }),
        fetchSessionAllocations({ date: anchorDate }),
      ]);
      setWeekSessions(sessionsRes.items || []);
      setWeekAllocations(allocationsRes.items || []);
      setLastUpdated(new Date());
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "The day could not be loaded.");
    } finally {
      setIsLoading(false);
    }
  }, [anchorDate]);

  const reload = useCallback(() => {
    if (viewMode === "month") {
      void loadMonth();
    } else if (viewMode === "week") {
      void loadWeek();
    } else {
      void loadDay();
    }
  }, [viewMode, loadMonth, loadWeek, loadDay]);

  useEffect(() => {
    void reload();
  }, [reload]);

  // Refresh after attendance changes and after session initialisation.
  useEffect(() => {
    const handler = () => reload();
    window.addEventListener("rollcall:attendance-changed", handler);
    window.addEventListener("rollcall:sessions-changed", handler);
    return () => {
      window.removeEventListener("rollcall:attendance-changed", handler);
      window.removeEventListener("rollcall:sessions-changed", handler);
    };
  }, [reload]);

  /* ------------------------------------------------------------------ */
  /* Derived data                                                        */
  /* ------------------------------------------------------------------ */

  const selectedDay: CalendarDaySummary | null = useMemo(() => {
    if (!monthData) return null;
    return monthData.days.find((day) => day.date === selectedDate) ?? null;
  }, [monthData, selectedDate]);

  const daySummary = useMemo(() => {
    if (!selectedDay || selectedDay.sessionCount === 0) return null;
    return {
      present: selectedDay.presentCount,
      absent: selectedDay.absentCount,
      pending: selectedDay.pendingCount,
      total: selectedDay.totalStudents,
    };
  }, [selectedDay]);

  const weekDays = useMemo(() => {
    const start = startOfWeekIso(anchorDate);
    return Array.from({ length: 7 }, (_, index) => addDaysIso(start, index));
  }, [anchorDate]);

  const sessionsByDate = useMemo(() => {
    const map = new Map<string, SessionItem[]>();
    for (const item of weekSessions) {
      const list = map.get(item.date) || [];
      list.push(item);
      map.set(item.date, list);
    }
    return map;
  }, [weekSessions]);

  const allocationsByDate = useMemo(() => {
    const map = new Map<string, SessionAllocation[]>();
    for (const item of weekAllocations) {
      const list = map.get(item.date) || [];
      list.push(item);
      map.set(item.date, list);
    }
    for (const list of map.values()) {
      list.sort((a, b) => (a.start_time || "").localeCompare(b.start_time || ""));
    }
    return map;
  }, [weekAllocations]);

  const filterSubject = (code?: string | null) =>
    selectedSubject === "ALL" || (code || "").toUpperCase() === selectedSubject.toUpperCase();

  /* ------------------------------------------------------------------ */
  /* Navigation                                                          */
  /* ------------------------------------------------------------------ */

  const shift = (direction: number) => {
    if (viewMode === "month") {
      const next = new Date(year, month + direction, 1);
      setAnchorDate(
        `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, "0")}-01`
      );
    } else if (viewMode === "week") {
      setAnchorDate(addDaysIso(anchorDate, direction * 7));
    } else {
      setAnchorDate(addDaysIso(anchorDate, direction));
    }
  };

  const goToday = () => {
    setAnchorDate(today);
    setSelectedDate(today);
  };

  const paddedBlanks = useMemo(() => {
    if (!monthData) return [];
    const first = new Date(year, month, 1).getDay();
    const offset = weekStartsMonday ? (first + 6) % 7 : first;
    return Array.from({ length: offset });
  }, [monthData, year, month, weekStartsMonday]);

  const labels = weekStartsMonday ? WEEKDAY_LABELS_MONDAY : WEEKDAY_LABELS;

  const periodLabel =
    viewMode === "month"
      ? `${monthData?.monthName ?? ""} ${year}`
      : viewMode === "week"
      ? `Week of ${formatIsoDate(weekDays[0])}`
      : formatIsoDate(anchorDate);

  /* ------------------------------------------------------------------ */
  /* Render                                                              */
  /* ------------------------------------------------------------------ */

  const dayPanel = (date: string, sessions: SessionItem[], allocations: SessionAllocation[]) => {
    if (sessions.length === 0) {
      return (
        <p className="text-[11px] text-[#A8A28E] py-3 text-center">
          No sessions on this date.
        </p>
      );
    }
    return (
      <ul className="space-y-2">
        {sessions.map((item) => {
          const allocation = allocations.find((a) => a.session_id === item.session_id);
          return (
            <li
              key={item.session_id}
              className="p-2.5 rounded-xl bg-white border border-[#E4DDCA] space-y-1"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-[11px] font-bold text-[#6C5119]">
                  {item.subject_code || item.subject || item.session_id}
                </span>
                <span className="text-[10px] font-semibold text-[#3F451F]">
                  {allocation ? `${allocation.start_time} - ${allocation.end_time}` : "Time not scheduled"}
                </span>
              </div>
              <p className="text-xs font-semibold text-[#24251C] truncate">{item.subject}</p>
              <div className="flex items-center justify-between gap-2 text-[10px] text-[#77735F]">
                <span className="truncate">
                  {allocation?.room_id ? `Room ${allocation.room_id}` : "Room not allocated"}
                </span>
                <Link
                  to={`/attendance?session=${encodeURIComponent(item.session_id)}`}
                  className="font-bold text-[#3F451F] hover:underline"
                >
                  Attendance
                </Link>
              </div>
            </li>
          );
        })}
      </ul>
    );
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-[#24251C] tracking-tight">
            Academic Calendar
          </h1>
          <p className="text-xs sm:text-sm text-[#77735F] mt-1">
            Real sessions, class slots and attendance straight from the RollCall AI backend.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-xl border border-[#E4DDCA] bg-[#FBF8F0] p-1 shadow-2xs">
            {(["month", "week", "day"] as CalendarViewMode[]).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => {
                  setViewMode(mode);
                  setDefaultView(mode);
                }}
                className={`px-3.5 py-1.5 rounded-lg text-xs font-bold capitalize transition-all cursor-pointer ${
                  viewMode === mode
                    ? "bg-[#3F451F] text-[#EDE8D8]"
                    : "text-[#77735F] hover:text-[#24251C]"
                }`}
              >
                {mode}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={reload}
            className="px-3.5 py-2 rounded-xl bg-[#FBF8F0] border border-[#E4DDCA] text-xs font-bold text-[#24251C] hover:bg-[#EDE8D8]/60 transition-colors cursor-pointer"
          >
            Refresh
          </button>
          <button
            type="button"
            onClick={goToday}
            className="px-3.5 py-2 rounded-xl bg-[#6C5119] text-white text-xs font-bold hover:bg-[#594214] transition-colors cursor-pointer"
          >
            Today
          </button>
        </div>
      </div>

      {/* Controls */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-2xs flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => shift(-1)}
            aria-label="Previous period"
            className="p-2 rounded-xl bg-[#F2EDE0] hover:bg-[#E4DDCA] text-[#24251C] transition-colors cursor-pointer"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <h2 className="text-base sm:text-lg font-bold text-[#24251C] min-w-[170px] text-center">
            {periodLabel}
          </h2>
          <button
            type="button"
            onClick={() => shift(1)}
            aria-label="Next period"
            className="p-2 rounded-xl bg-[#F2EDE0] hover:bg-[#E4DDCA] text-[#24251C] transition-colors cursor-pointer"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {subjectOptions.length > 1 && (
            <label className="flex items-center gap-2 text-xs font-semibold text-[#77735F]">
              Subject
              <select
                value={selectedSubject}
                onChange={(e) => setSelectedSubject(e.target.value)}
                className="bg-[#F2EDE0] border border-[#E4DDCA] rounded-xl px-3 py-1.5 text-xs text-[#24251C] focus:outline-none focus:border-[#3F451F] cursor-pointer"
              >
                {subjectOptions.map((code) => (
                  <option key={code} value={code}>
                    {code === "ALL" ? "All my subjects" : code}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="flex items-center gap-2 text-xs font-semibold text-[#77735F] cursor-pointer">
            <input
              type="checkbox"
              checked={weekStartsMonday}
              onChange={(e) => setWeekStartsMonday(e.target.checked)}
              className="accent-[#6C5119] w-4 h-4"
            />
            Week starts Monday
          </label>
          <label className="flex items-center gap-2 text-xs font-semibold text-[#77735F] cursor-pointer">
            <input
              type="checkbox"
              checked={showHeatmap}
              onChange={(e) => setShowHeatmap(e.target.checked)}
              className="accent-[#6C5119] w-4 h-4"
            />
            Heatmap
          </label>
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-800 flex items-center justify-between gap-3">
          <span>{error}</span>
          <button
            type="button"
            onClick={reload}
            className="font-bold underline cursor-pointer"
          >
            Retry
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main calendar */}
        <div className="lg:col-span-2 bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 sm:p-5 shadow-2xs space-y-4">
          {isLoading ? (
            <div className="py-16 text-center text-[#77735F]">
              <div className="inline-block animate-spin w-6 h-6 border-2 border-[#3F451F] border-t-transparent rounded-full mb-2" />
              <p className="text-sm font-medium">Loading the academic calendar…</p>
            </div>
          ) : viewMode === "month" ? (
            monthData && (
              <>
                <div className="grid grid-cols-7 gap-1 sm:gap-2 text-center text-[10px] sm:text-xs font-bold text-[#77735F] uppercase tracking-wider pb-1">
                  {labels.map((label) => (
                    <div key={label}>{label}</div>
                  ))}
                </div>

                <div className="grid grid-cols-7 gap-1 sm:gap-2">
                  {paddedBlanks.map((_, index) => (
                    <div key={`blank-${index}`} className="h-16 sm:h-20 rounded-xl bg-transparent" />
                  ))}

                  {monthData.days.map((day) => {
                    const isSelected = selectedDate === day.date;
                    const hasSessions = day.sessionCount > 0;
                    let bandBg = "bg-white hover:bg-[#F2EDE0]";
                    let bandBorder = "border-[#E4DDCA]";
                    let bandText = "text-[#77735F]";

                    if (hasSessions && showHeatmap) {
                      if (day.healthBand === "GREEN") {
                        bandBg = isSelected ? "bg-emerald-100" : "bg-emerald-50 hover:bg-emerald-100";
                        bandBorder = "border-emerald-300";
                        bandText = "text-emerald-900";
                      } else if (day.healthBand === "YELLOW") {
                        bandBg = isSelected ? "bg-amber-100" : "bg-amber-50 hover:bg-amber-100";
                        bandBorder = "border-amber-300";
                        bandText = "text-amber-900";
                      } else if (day.healthBand === "RED") {
                        bandBg = isSelected ? "bg-rose-100" : "bg-rose-50 hover:bg-rose-100";
                        bandBorder = "border-rose-300";
                        bandText = "text-rose-900";
                      }
                    }

                    return (
                      <button
                        key={day.date}
                        type="button"
                        onClick={() => setSelectedDate(day.date)}
                        className={`h-16 sm:h-20 rounded-xl border p-1.5 sm:p-2 text-left flex flex-col justify-between transition-all cursor-pointer min-w-0 ${bandBg} ${bandBorder} ${
                          isSelected ? "ring-2 ring-[#3F451F]" : ""
                        } ${day.isToday ? "border-[#A77A13]" : ""}`}
                        aria-label={`${formatIsoDate(day.date)}, ${day.sessionCount} sessions`}
                      >
                        <div className="flex items-center justify-between w-full">
                          <span className="text-xs sm:text-sm font-bold text-[#24251C]">
                            {day.dayNumber}
                          </span>
                          {hasSessions && (
                            <span className="text-[9px] font-bold px-1.5 py-0.2 rounded bg-white/80 text-[#3F451F]">
                              {day.sessionCount}
                            </span>
                          )}
                        </div>
                        {hasSessions ? (
                          <div className="truncate">
                            <span className={`text-[10px] sm:text-xs font-bold block ${bandText}`}>
                              {day.attendanceRate !== null
                                ? `${day.attendanceRate.toFixed(0)}%`
                                : "—"}
                            </span>
                            <span className="text-[8px] sm:text-[9px] text-[#77735F] hidden sm:block truncate">
                              {day.healthBandLabel}
                            </span>
                          </div>
                        ) : (
                          <span className="text-[9px] text-[#A8A28E] hidden sm:block">No sessions</span>
                        )}
                      </button>
                    );
                  })}
                </div>

                <div className="pt-3 border-t border-[#E4DDCA] flex flex-wrap items-center justify-between gap-3 text-xs">
                  <div className="flex items-center gap-3 flex-wrap">
                    <span className="font-semibold text-[#77735F]">Health bands:</span>
                    <span className="flex items-center gap-1.5">
                      <span className="w-3 h-3 rounded-full bg-emerald-500" />
                      <span className="text-[#24251C]">Green</span>
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span className="w-3 h-3 rounded-full bg-amber-500" />
                      <span className="text-[#24251C]">Yellow</span>
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span className="w-3 h-3 rounded-full bg-rose-500" />
                      <span className="text-[#24251C]">Red</span>
                    </span>
                  </div>
                  <span className="text-xs italic font-medium text-[#77735F] bg-[#F2EDE0] px-2.5 py-1 rounded-lg border border-[#E4DDCA]">
                    {monthData.totalSessions} session(s) this month
                  </span>
                </div>
              </>
            )
          ) : viewMode === "week" ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-7 gap-3">
              {weekDays.map((date) => {
                const sessions = (sessionsByDate.get(date) || []).filter((s) =>
                  filterSubject(s.subject_code || s.subject)
                );
                const allocations = allocationsByDate.get(date) || [];
                const isToday = date === today;
                return (
                  <div
                    key={date}
                    className={`rounded-xl border p-2.5 min-h-[120px] ${
                      isToday ? "border-[#A77A13] bg-[#EDE8D8]/30" : "border-[#E4DDCA] bg-white"
                    }`}
                  >
                    <p className="text-[11px] font-black uppercase tracking-wider text-[#77735F]">
                      {weekdayOfIsoDate(date).slice(0, 3)} {date.slice(8)}
                    </p>
                    <div className="mt-2 space-y-1.5">
                      {sessions.length === 0 ? (
                        <p className="text-[10px] text-[#A8A28E]">No sessions</p>
                      ) : (
                        sessions.map((item) => {
                          const allocation = allocations.find(
                            (a) => a.session_id === item.session_id
                          );
                          return (
                            <button
                              key={item.session_id}
                              type="button"
                              onClick={() => {
                                setSelectedDate(date);
                                setAnchorDate(date);
                              }}
                              className="w-full text-left p-2 rounded-lg bg-[#F2EDE0] border border-[#E4DDCA] hover:border-[#A77A13] transition-colors cursor-pointer"
                            >
                              <span className="block text-[10px] font-bold text-[#3F451F] truncate">
                                {item.subject_code || item.subject}
                              </span>
                              <span className="block text-[9px] text-[#77735F]">
                                {allocation
                                  ? `${allocation.start_time}-${allocation.end_time}`
                                  : "No time"}
                              </span>
                            </button>
                          );
                        })
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="space-y-3">
              {(() => {
                const sessions = (sessionsByDate.get(anchorDate) || []).filter((s) =>
                  filterSubject(s.subject_code || s.subject)
                );
                const allocations = allocationsByDate.get(anchorDate) || [];
                if (sessions.length === 0) {
                  return (
                    <div className="py-12 text-center text-[#77735F] bg-[#F2EDE0]/50 rounded-xl border border-dashed border-[#E4DDCA]">
                      <p className="text-sm font-bold text-[#24251C]">No sessions on this day</p>
                      <p className="text-xs mt-1">
                        The timetable has no classes scheduled for{" "}
                        {formatIsoDate(anchorDate)}.
                      </p>
                    </div>
                  );
                }
                return (
                  <ul className="space-y-2.5">
                    {sessions.map((item) => {
                      const allocation = allocations.find((a) => a.session_id === item.session_id);
                      return (
                        <li
                          key={item.session_id}
                          className="p-4 rounded-xl bg-white border border-[#E4DDCA] flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3"
                        >
                          <div>
                            <p className="font-mono text-[11px] font-bold text-[#6C5119]">
                              {item.subject_code || item.session_id}
                            </p>
                            <p className="text-sm font-bold text-[#24251C]">{item.subject}</p>
                            <p className="text-[11px] text-[#77735F] mt-0.5">
                              {allocation
                                ? `Room ${allocation.room_id} · ${allocation.start_time} - ${allocation.end_time}`
                                : "No room or time allocated yet"}
                            </p>
                          </div>
                          <Link
                            to={`/attendance?session=${encodeURIComponent(item.session_id)}`}
                            className="self-start sm:self-auto px-3.5 py-2 rounded-xl bg-[#3F451F] text-[#EDE8D8] text-xs font-bold hover:bg-[#343919] transition-colors"
                          >
                            Open attendance
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                );
              })()}
            </div>
          )}

          {lastUpdated && (
            <p className="text-[11px] text-[#77735F] pt-2 border-t border-[#E4DDCA]/60">
              Last updated {lastUpdated.toLocaleTimeString()} · data served by the RollCall AI
              backend
            </p>
          )}
        </div>

        {/* Selected day panel */}
        <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 sm:p-5 shadow-2xs flex flex-col space-y-4">
          <div className="pb-3 border-b border-[#E4DDCA] flex items-center justify-between gap-2">
            <div>
              <h3 className="text-base font-bold text-[#24251C]">Selected day</h3>
              <p className="text-xs text-[#77735F]">
                {formatIsoDate(selectedDate)} · {weekdayOfIsoDate(selectedDate)}
              </p>
            </div>
            {selectedDay && selectedDay.sessionCount > 0 && (
              <span className="px-2.5 py-1 rounded-lg text-xs font-bold bg-[#3F451F] text-[#FBF8F0]">
                {selectedDay.sessionCount} session(s)
              </span>
            )}
          </div>

          {viewMode === "month" && selectedDay && selectedDay.sessionCount > 0 && (
            <div className="grid grid-cols-3 gap-2 text-center">
              <div className="p-2.5 rounded-xl bg-[#F2EDE0] border border-[#E4DDCA]">
                <p className="text-[10px] font-bold uppercase tracking-wider text-[#77735F]">
                  Present
                </p>
                <p className="text-lg font-black text-emerald-700">{selectedDay.presentCount}</p>
              </div>
              <div className="p-2.5 rounded-xl bg-[#F2EDE0] border border-[#E4DDCA]">
                <p className="text-[10px] font-bold uppercase tracking-wider text-[#77735F]">
                  Absent
                </p>
                <p className="text-lg font-black text-rose-700">{selectedDay.absentCount}</p>
              </div>
              <div className="p-2.5 rounded-xl bg-[#F2EDE0] border border-[#E4DDCA]">
                <p className="text-[10px] font-bold uppercase tracking-wider text-[#77735F]">
                  Pending
                </p>
                <p className="text-lg font-black text-amber-700">{selectedDay.pendingCount}</p>
              </div>
            </div>
          )}

          {daySummary && daySummary.total > 0 && (
            <p className="text-xs text-[#77735F]">
              {daySummary.present} of {daySummary.total} attendance marks are present on this day.
            </p>
          )}

          <div className="flex-1">
            {viewMode === "month" ? (
              selectedDay && selectedDay.sessionCount > 0 ? (
                dayPanel(selectedDay.date, selectedDay.sessions, selectedDay.allocations)
              ) : (
                <div className="py-10 text-center text-[#77735F] bg-[#F2EDE0]/50 rounded-xl border border-dashed border-[#E4DDCA]">
                  <p className="text-xs font-bold text-[#24251C]">No sessions conducted</p>
                  <p className="text-[11px] mt-0.5">
                    The timetable has no classes on {formatIsoDate(selectedDate)}.
                  </p>
                </div>
              )
            ) : viewMode === "week" ? (
              <div className="space-y-3 max-h-[420px] overflow-y-auto pr-1">
                {weekDays.map((date) => (
                  <div key={date}>
                    <p className="text-[11px] font-black uppercase tracking-wider text-[#77735F] mb-1.5">
                      {weekdayOfIsoDate(date)} · {date.slice(8)}
                    </p>
                    {dayPanel(
                      date,
                      (sessionsByDate.get(date) || []).filter((s) =>
                        filterSubject(s.subject_code || s.subject)
                      ),
                      allocationsByDate.get(date) || []
                    )}
                  </div>
                ))}
              </div>
            ) : (
              dayPanel(
                anchorDate,
                (sessionsByDate.get(anchorDate) || []).filter((s) =>
                  filterSubject(s.subject_code || s.subject)
                ),
                allocationsByDate.get(anchorDate) || []
              )
            )}
          </div>

          <div className="pt-3 border-t border-[#E4DDCA] text-[11px] text-[#77735F]">
            Attendance figures are read from the server analytics endpoint. A day without
            sessions is never shown as 0% attendance.
          </div>
        </div>
      </div>
    </div>
  );
}
