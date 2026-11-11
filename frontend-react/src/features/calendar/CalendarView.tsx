"use client";

import React, { useEffect, useState, useCallback, useMemo } from "react";
import {
  loadMonthCalendarData,
  fetchDailyAttendanceSummary,
  exportCalendarIcs,
  type CalendarDaySummary,
  type CalendarMonthData,
} from "@/services/api/calendar";
import { useAuth } from "@/hooks/useAuth";
import type { VerifiedSummaryReport } from "@/types/dashboard";

export function CalendarView() {
  const { isAdmin, session } = useAuth();

  // Current calendar view date: default to 2026-10 (matching academic sessions in DB)
  const [currentYear, setCurrentYear] = useState(2026);
  const [currentMonth, setCurrentMonth] = useState(9); // October = index 9

  const [calendarData, setCalendarData] = useState<CalendarMonthData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Subject Filter
  const [selectedSubject, setSelectedSubject] = useState("ALL");

  // Selected Day & Daily Detail Panel
  const [selectedDay, setSelectedDay] = useState<CalendarDaySummary | null>(null);
  const [, setDailySummary] = useState<VerifiedSummaryReport | null>(null);
  const [isDailyLoading, setIsDailyLoading] = useState(false);

  // Export State (Admin only)
  const [isExporting, setIsExporting] = useState(false);
  const [exportNotice, setExportNotice] = useState<string | null>(null);

  // Authorized subjects for filter dropdown
  const allowedSubjectOptions = useMemo(() => {
    if (isAdmin) {
      return ["ALL", "DIST-SYS", "DB-SYS", "ML", "CN", "NET-SEC", "ES"];
    }
    const facultyCodes = session?.subjectCodes || [];
    return facultyCodes.length > 0 ? ["ALL", ...facultyCodes] : ["ALL", "DIST-SYS", "ML"];
  }, [isAdmin, session]);

  const loadMonth = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await loadMonthCalendarData(currentYear, currentMonth, selectedSubject);
      setCalendarData(data);

      // Auto-select first day with sessions if nothing selected
      const firstActive = data.days.find((d) => d.sessionCount > 0);
      if (firstActive) {
        setSelectedDay(firstActive);
      } else {
        setSelectedDay(data.days[0] || null);
      }
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Failed to load monthly attendance calendar.");
      }
    } finally {
      setIsLoading(false);
    }
  }, [currentYear, currentMonth, selectedSubject]);

  useEffect(() => {
    let isMounted = true;
    Promise.resolve().then(() => {
      if (isMounted) void loadMonth();
    });
    return () => {
      isMounted = false;
    };
  }, [loadMonth]);

  // When a day is clicked, load daily summary details from server
  const handleSelectDay = async (day: CalendarDaySummary) => {
    setSelectedDay(day);
    if (day.sessionCount === 0) {
      setDailySummary(null);
      return;
    }

    setIsDailyLoading(true);
    try {
      const summary = await fetchDailyAttendanceSummary(day.date);
      setDailySummary(summary);
    } catch {
      setDailySummary(null);
    } finally {
      setIsDailyLoading(false);
    }
  };

  const handlePrevMonth = () => {
    if (currentMonth === 0) {
      setCurrentMonth(11);
      setCurrentYear((y) => y - 1);
    } else {
      setCurrentMonth((m) => m - 1);
    }
  };

  const handleNextMonth = () => {
    if (currentMonth === 11) {
      setCurrentMonth(0);
      setCurrentYear((y) => y + 1);
    } else {
      setCurrentMonth((m) => m + 1);
    }
  };

  const handleExportIcs = async () => {
    if (!isAdmin) return;
    setIsExporting(true);
    setExportNotice(null);

    const monthStr = `${currentYear}-${String(currentMonth + 1).padStart(2, "0")}`;
    const result = await exportCalendarIcs({
      month: monthStr,
      subject: selectedSubject !== "ALL" ? selectedSubject : undefined,
    });

    if (result.blob) {
      const url = window.URL.createObjectURL(result.blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `RollCall_Attendance_${monthStr}.ics`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
      setExportNotice("Academic schedule exported to iCalendar (.ics).");
    } else if (result.isPending && result.message) {
      setExportNotice(result.message);
    }
    setIsExporting(false);
  };

  // Day of week padding for the first day of the month
  const firstDayOfWeek = new Date(currentYear, currentMonth, 1).getDay(); // 0 = Sun, 1 = Mon ...
  const paddedBlanks = Array.from({ length: firstDayOfWeek });

  return (
    <div className="space-y-6">
      {/* Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-[#24251C] tracking-tight">
            Attendance Calendar & Class Health Heatmap
          </h1>
          <p className="text-sm text-[#77735F] mt-0.5">
            Aggregated institutional calendar view with health band colour coding and session drill-downs.
          </p>
        </div>

        {/* ADMIN only Export .ics Button */}
        {isAdmin && (
          <button
            onClick={() => void handleExportIcs()}
            disabled={isExporting}
            className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-[#3F451F] text-[#FBF8F0] text-sm font-semibold rounded-xl hover:bg-[#323719] transition-all shadow-sm disabled:opacity-50 cursor-pointer"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
            <span>{isExporting ? "Exporting..." : "Export .ics"}</span>
          </button>
        )}
      </div>

      {/* Export Notice / Dependency Banner */}
      {exportNotice && (
        <div className="p-3.5 bg-amber-50 border border-amber-200 rounded-xl text-xs text-amber-900 flex items-center justify-between">
          <span>{exportNotice}</span>
          <button
            onClick={() => setExportNotice(null)}
            className="text-xs hover:underline cursor-pointer"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Calendar Controls & Navigation */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-sm flex flex-col sm:flex-row items-center justify-between gap-3">
        {/* Month & Year Navigation */}
        <div className="flex items-center gap-3">
          <button
            onClick={handlePrevMonth}
            className="p-2 rounded-xl bg-[#F2EDE0] hover:bg-[#E4DDCA] text-[#24251C] transition-colors cursor-pointer"
            title="Previous Month"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>

          <h2 className="text-base sm:text-lg font-bold text-[#24251C] min-w-[160px] text-center">
            {calendarData?.monthName || "October"} {currentYear}
          </h2>

          <button
            onClick={handleNextMonth}
            className="p-2 rounded-xl bg-[#F2EDE0] hover:bg-[#E4DDCA] text-[#24251C] transition-colors cursor-pointer"
            title="Next Month"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </button>
        </div>

        {/* Subject Filter & Reset */}
        <div className="flex items-center gap-2 w-full sm:w-auto">
          <span className="text-xs font-semibold text-[#77735F]">Subject:</span>
          <select
            value={selectedSubject}
            onChange={(e) => setSelectedSubject(e.target.value)}
            className="bg-[#F2EDE0] border border-[#E4DDCA] rounded-xl px-3 py-1.5 text-xs text-[#24251C] focus:outline-none focus:border-[#3F451F]"
          >
            {allowedSubjectOptions.map((sub) => (
              <option key={sub} value={sub}>
                {sub === "ALL" ? "All Authorized Subjects" : sub}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Main Grid & Daily Detail Container */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Calendar Heatmap Grid (2 Cols on Large, 1 Col on Mobile 375px) */}
        <div className="lg:col-span-2 bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 sm:p-5 shadow-sm space-y-4">
          {isLoading ? (
            <div className="p-16 text-center text-[#77735F]">
              <div className="inline-block animate-spin w-6 h-6 border-2 border-[#3F451F] border-t-transparent rounded-full mb-2" />
              <p className="text-sm font-medium">Loading calendar schedule...</p>
            </div>
          ) : error ? (
            <div className="p-10 text-center">
              <p className="text-sm text-rose-600 mb-3">{error}</p>
              <button
                onClick={() => void loadMonth()}
                className="px-4 py-1.5 bg-[#3F451F] text-[#FBF8F0] text-xs font-semibold rounded-lg hover:bg-[#323719] cursor-pointer"
              >
                Retry
              </button>
            </div>
          ) : (
            <>
              {/* Day of Week Headers */}
              <div className="grid grid-cols-7 gap-1 sm:gap-2 text-center text-[10px] sm:text-xs font-bold text-[#77735F] uppercase tracking-wider pb-1">
                <div>Sun</div>
                <div>Mon</div>
                <div>Tue</div>
                <div>Wed</div>
                <div>Thu</div>
                <div>Fri</div>
                <div>Sat</div>
              </div>

              {/* Month Days Grid - Highly Responsive (min-w-0 for 375px mobile) */}
              <div className="grid grid-cols-7 gap-1 sm:gap-2">
                {/* Blanks for offset */}
                {paddedBlanks.map((_, idx) => (
                  <div key={`blank-${idx}`} className="h-14 sm:h-20 rounded-xl bg-transparent" />
                ))}

                {/* Days */}
                {calendarData?.days.map((day) => {
                  const isSelected = selectedDay?.date === day.date;
                  const hasSessions = day.sessionCount > 0;

                  // Health band styling: Green >85%, Yellow 70-85%, Red <70%
                  let bandBg = "bg-white hover:bg-[#F2EDE0]";
                  let bandBorder = "border-[#E4DDCA]";
                  let bandText = "text-[#77735F]";

                  if (hasSessions) {
                    if (day.healthBand === "GREEN") {
                      bandBg = isSelected ? "bg-emerald-100" : "bg-emerald-50 hover:bg-emerald-100";
                      bandBorder = "border-emerald-300";
                      bandText = "text-emerald-900";
                    } else if (day.healthBand === "YELLOW") {
                      bandBg = isSelected ? "bg-amber-100" : "bg-amber-50 hover:bg-amber-100";
                      bandBorder = "border-amber-300";
                      bandText = "text-amber-900";
                    } else {
                      bandBg = isSelected ? "bg-rose-100" : "bg-rose-50 hover:bg-rose-100";
                      bandBorder = "border-rose-300";
                      bandText = "text-rose-900";
                    }
                  } else {
                    // Days without sessions: NOT zero attendance, neutral tone
                    bandBg = isSelected ? "bg-[#EDE8D8]" : "bg-[#FBF8F0]/70 hover:bg-[#F2EDE0]";
                    bandBorder = "border-[#E4DDCA]/60";
                    bandText = "text-[#A8A28E]";
                  }

                  return (
                    <button
                      key={day.date}
                      onClick={() => void handleSelectDay(day)}
                      className={`h-14 sm:h-20 rounded-xl border p-1 sm:p-2 text-left flex flex-col justify-between transition-all cursor-pointer min-w-0 ${bandBg} ${bandBorder} ${
                        isSelected ? "ring-2 ring-[#3F451F] shadow-sm" : ""
                      }`}
                    >
                      <div className="flex items-center justify-between w-full">
                        <span className="text-xs sm:text-sm font-bold text-[#24251C]">
                          {day.dayNumber}
                        </span>
                        {hasSessions && (
                          <span className="hidden sm:inline-block text-[9px] font-bold px-1.5 py-0.2 rounded bg-white/80 text-[#3F451F]">
                            {day.sessionCount} {day.sessionCount === 1 ? "class" : "classes"}
                          </span>
                        )}
                      </div>

                      {hasSessions ? (
                        <div className="truncate">
                          <span className={`text-[10px] sm:text-xs font-bold block ${bandText}`}>
                            {day.attendanceRate !== null ? `${day.attendanceRate.toFixed(0)}%` : "—"}
                          </span>
                          <span className="text-[8px] sm:text-[9px] text-[#77735F] hidden sm:block truncate">
                            {day.healthBandLabel}
                          </span>
                        </div>
                      ) : (
                        <span className="text-[9px] text-[#A8A28E] hidden sm:block truncate">
                          No sessions
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>

              {/* Legend with Required Caption */}
              <div className="pt-3 border-t border-[#E4DDCA] flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
                <div className="flex items-center gap-3 flex-wrap">
                  <span className="font-semibold text-[#77735F]">Health Bands:</span>
                  <div className="flex items-center gap-1.5">
                    <span className="w-3 h-3 rounded-full bg-emerald-500" />
                    <span className="text-[#24251C]">Green (&gt;85%)</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-3 h-3 rounded-full bg-amber-500" />
                    <span className="text-[#24251C]">Yellow (70–85%)</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-3 h-3 rounded-full bg-rose-500" />
                    <span className="text-[#24251C]">Red (&lt;70%)</span>
                  </div>
                </div>

                {/* Mandatory Prompt Explanation */}
                <span className="text-xs italic font-medium text-[#77735F] bg-[#F2EDE0] px-2.5 py-1 rounded-lg border border-[#E4DDCA]">
                  &ldquo;Colours show class health, not eligibility.&rdquo;
                </span>
              </div>
            </>
          )}
        </div>

        {/* Daily Detail Panel */}
        <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 sm:p-5 shadow-sm flex flex-col justify-between space-y-4">
          <div>
            <div className="pb-3 border-b border-[#E4DDCA] flex items-center justify-between">
              <div>
                <h3 className="text-base font-bold text-[#24251C]">
                  Daily Session Details
                </h3>
                <p className="text-xs text-[#77735F]">
                  {selectedDay ? selectedDay.date : "Select a date on the calendar"}
                </p>
              </div>
              {selectedDay && selectedDay.sessionCount > 0 && (
                <span className="px-2.5 py-1 rounded-lg text-xs font-bold bg-[#3F451F] text-[#FBF8F0]">
                  {selectedDay.sessionCount} {selectedDay.sessionCount === 1 ? "Session" : "Sessions"}
                </span>
              )}
            </div>

            {/* Daily Content */}
            <div className="mt-4 space-y-3">
              {isDailyLoading ? (
                <div className="p-8 text-center text-[#77735F]">
                  <div className="inline-block animate-spin w-5 h-5 border-2 border-[#3F451F] border-t-transparent rounded-full mb-1" />
                  <p className="text-xs">Loading sessions for this date...</p>
                </div>
              ) : !selectedDay || selectedDay.sessionCount === 0 ? (
                <div className="p-8 text-center text-[#77735F] bg-[#F2EDE0]/50 rounded-xl border border-dashed border-[#E4DDCA]">
                  <svg className="w-8 h-8 mx-auto text-[#A8A28E] mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                  </svg>
                  <p className="text-xs font-bold text-[#24251C]">No sessions conducted</p>
                  <p className="text-[11px] text-[#77735F] mt-0.5">
                    No academic classes or lab practicals are scheduled for this date.
                  </p>
                </div>
              ) : (
                <div className="space-y-3">
                  {/* Daily Metric Overview */}
                  {selectedDay.attendanceRate !== null && (
                    <div className="p-3 bg-[#F2EDE0] border border-[#E4DDCA] rounded-xl flex items-center justify-between text-xs">
                      <div>
                        <span className="text-[#77735F] block">Day Attendance</span>
                        <span className="text-sm font-bold text-[#24251C]">
                          {selectedDay.attendanceRate.toFixed(1)}%
                        </span>
                      </div>
                      <div className="text-right">
                        <span className="text-[#77735F] block">Present / Total</span>
                        <span className="text-xs font-mono font-bold text-[#3F451F]">
                          {selectedDay.presentCount} / {selectedDay.totalStudents}
                        </span>
                      </div>
                    </div>
                  )}

                  {/* Session List for Day */}
                  <div className="space-y-2.5 max-h-[340px] overflow-y-auto pr-1">
                    {selectedDay.sessions.map((sess) => {
                      const roomName = sess.allocations?.[0]?.room_id || "LH-101";
                      const facultyId = sess.allocations?.[0]?.teacher_id || sess.teacher_id || "faculty_ml";
                      const subjCode = sess.subject_code || sess.subject || "Academic Session";

                      return (
                        <div
                          key={sess.session_id}
                          className="p-3 bg-white border border-[#E4DDCA] rounded-xl shadow-2xs space-y-1.5"
                        >
                          <div className="flex items-center justify-between">
                            <span className="font-mono text-xs font-bold text-[#6C5119]">
                              {subjCode}
                            </span>
                            <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-[#3F451F]/10 text-[#3F451F]">
                              {roomName}
                            </span>
                          </div>
                          <p className="text-xs font-semibold text-[#24251C]">
                            Session {sess.session_id}
                          </p>
                          <div className="flex items-center justify-between text-[11px] text-[#77735F] pt-1 border-t border-[#E4DDCA]/50">
                            <span>Faculty: {facultyId}</span>
                            <span className="font-semibold text-emerald-700">
                              Status: CONFIRMED
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="pt-3 border-t border-[#E4DDCA] text-[11px] text-[#77735F]">
            Data synced with authoritative RollCall AI analytics engine.
          </div>
        </div>
      </div>
    </div>
  );
}
