import { apiClient } from "@/services/api/client";
import {
  fetchSessionAllocations,
  fetchSessions,
  type SessionAllocation,
  type SessionItem,
} from "@/services/api/sessions";
import { fetchMetaConfig } from "@/services/api/defaulters";
import type { VerifiedSummaryReport } from "@/types/dashboard";

export interface CalendarDaySummary {
  date: string; // YYYY-MM-DD
  dayNumber: number;
  sessionCount: number;
  /** null when the day has no sessions - never 0 for a non-teaching day. */
  attendanceRate: number | null;
  presentCount: number;
  absentCount: number;
  pendingCount: number;
  totalStudents: number;
  healthBand: "GREEN" | "YELLOW" | "RED" | "NONE";
  healthBandLabel: string;
  sessions: SessionItem[];
  allocations: SessionAllocation[];
  /** True for the calendar day of "today" in the browser timezone. */
  isToday: boolean;
}

export interface CalendarMonthData {
  year: number;
  month: number; // 0-indexed
  monthName: string;
  days: CalendarDaySummary[];
  totalSessions: number;
}

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function isoDate(year: number, month: number, day: number): string {
  return `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

export async function fetchDailyAttendanceSummary(date: string): Promise<VerifiedSummaryReport> {
  return apiClient.get<VerifiedSummaryReport>(`/api/v1/analytics/date/${date}/summary`);
}

export async function exportCalendarIcs(params?: {
  month?: string;
  subject?: string;
}): Promise<{ blob?: Blob; isPending?: boolean; message?: string }> {
  try {
    const queryParams: Record<string, string | number | boolean | undefined | null> = {};
    if (params?.month) queryParams.month = params.month;
    if (params?.subject) queryParams.subject = params.subject;

    const blob = await apiClient.get<Blob>(
      "/api/v1/calendar/export.ics",
      Object.keys(queryParams).length ? queryParams : undefined,
      { responseType: "blob" }
    );
    return { blob };
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return {
      isPending: true,
      message: `Backend endpoint pending: GET /api/v1/calendar/export.ics is not implemented on the server. (${msg})`,
    };
  }
}

/**
 * Load a month of real calendar data.
 *
 * Sessions come from the backend, class slots (room / batch / time) from the
 * session allocations endpoint and the attendance figures from the analytics
 * summary of every day that actually has sessions. No attendance value is
 * ever invented in the browser.
 */
export async function loadMonthCalendarData(
  year: number,
  month: number,
  subjectFilter?: string,
  todayIso?: string
): Promise<CalendarMonthData> {
  const firstDay = isoDate(year, month, 1);
  const lastDay = isoDate(year, month, new Date(year, month + 1, 0).getDate());

  const [sessionsRes, allocationsRes, meta] = await Promise.all([
    fetchSessions({ limit: 200, from_date: firstDay, to_date: lastDay }),
    fetchSessionAllocations({ from_date: firstDay, to_date: lastDay }).catch(() => ({
      items: [] as SessionAllocation[],
      total: 0,
    })),
    fetchMetaConfig().catch(() => ({
      attendance_bands: { green_above_percent: 85.0, yellow_from_percent: 70.0 },
    })),
  ]);

  let allSessions = sessionsRes.items || [];
  if (subjectFilter && subjectFilter !== "ALL") {
    allSessions = allSessions.filter(
      (s) => (s.subject_code || s.subject || "").toUpperCase() === subjectFilter.toUpperCase()
    );
  }

  const sessionIds = new Set(allSessions.map((s) => s.session_id));
  const allocations = (allocationsRes.items || []).filter((a) =>
    sessionIds.has(a.session_id)
  );

  const dateMap = new Map<string, SessionItem[]>();
  for (const s of allSessions) {
    const list = dateMap.get(s.date) || [];
    list.push(s);
    dateMap.set(s.date, list);
  }

  const allocationMap = new Map<string, SessionAllocation[]>();
  for (const a of allocations) {
    const list = allocationMap.get(a.date) || [];
    list.push(a);
    allocationMap.set(a.date, list);
  }

  const greenThreshold = meta.attendance_bands?.green_above_percent ?? 85.0;
  const yellowThreshold = meta.attendance_bands?.yellow_from_percent ?? 70.0;

  const numDays = new Date(year, month + 1, 0).getDate();
  const days: CalendarDaySummary[] = [];
  let totalSessionsInMonth = 0;

  for (let day = 1; day <= numDays; day++) {
    const dateStr = isoDate(year, month, day);
    const daySessions = (dateMap.get(dateStr) || []).sort((a, b) =>
      (a.subject_code || a.subject || "").localeCompare(b.subject_code || b.subject || "")
    );
    const dayAllocations = allocationMap.get(dateStr) || [];

    if (daySessions.length === 0) {
      days.push({
        date: dateStr,
        dayNumber: day,
        sessionCount: 0,
        attendanceRate: null,
        presentCount: 0,
        absentCount: 0,
        pendingCount: 0,
        totalStudents: 0,
        healthBand: "NONE",
        healthBandLabel: "No sessions",
        sessions: [],
        allocations: [],
        isToday: dateStr === todayIso,
      });
      continue;
    }

    totalSessionsInMonth += daySessions.length;

    // The attendance figures come from the authoritative analytics endpoint.
    let present = 0;
    let absent = 0;
    let pending = 0;
    let total = 0;
    let rate: number | null = null;

    try {
      const summary = await fetchDailyAttendanceSummary(dateStr);
      const overall = summary?.overall;
      if (overall) {
        present = Number(overall.present ?? 0);
        absent = Number(overall.absent ?? 0);
        pending = Number(overall.pending ?? 0) + Number(overall.unreviewed ?? 0);
        total = Number(overall.total ?? 0);
        rate = overall.percentage ?? null;
      }
    } catch {
      // The day keeps its sessions but without attendance figures.
      rate = null;
    }

    let healthBand: "GREEN" | "YELLOW" | "RED" | "NONE" = "GREEN";
    let healthBandLabel = `Green (>${greenThreshold}%)`;
    if (rate === null) {
      healthBand = "NONE";
      healthBandLabel = "Attendance not available";
    } else if (rate > greenThreshold) {
      healthBand = "GREEN";
      healthBandLabel = `Green (>${greenThreshold}%)`;
    } else if (rate >= yellowThreshold) {
      healthBand = "YELLOW";
      healthBandLabel = `Yellow (${yellowThreshold}–${greenThreshold}%)`;
    } else {
      healthBand = "RED";
      healthBandLabel = `Red (<${yellowThreshold}%)`;
    }

    days.push({
      date: dateStr,
      dayNumber: day,
      sessionCount: daySessions.length,
      attendanceRate: rate,
      presentCount: present,
      absentCount: absent,
      pendingCount: pending,
      totalStudents: total,
      healthBand,
      healthBandLabel,
      sessions: daySessions,
      allocations: dayAllocations,
      isToday: dateStr === todayIso,
    });
  }

  return {
    year,
    month,
    monthName: MONTH_NAMES[month],
    days,
    totalSessions: totalSessionsInMonth,
  };
}
