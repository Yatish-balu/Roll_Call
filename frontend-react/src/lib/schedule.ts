/**
 * Institutional academic day policy (09:00 - 17:00).
 *
 * The same rule is enforced by the FastAPI backend
 * (`app/schemas/timetable.py::validate_academic_window`). The frontend copy
 * exists to give immediate, clear feedback - it is never the only guard.
 */

export const ACADEMIC_DAY_START = "09:00";
export const ACADEMIC_DAY_END = "17:00";

export interface WindowValidation {
  valid: boolean;
  message?: string;
}

/** Convert an "HH:MM" string into minutes since midnight. */
export function toMinutes(value: string): number | null {
  const match = /^([01]\d|2[0-3]):([0-5]\d)$/.exec(value.trim());
  if (!match) return null;
  return Number(match[1]) * 60 + Number(match[2]);
}

/** Format minutes since midnight as an "HH:MM" string. */
export function fromMinutes(minutes: number): string {
  const normalised = ((minutes % 1440) + 1440) % 1440;
  const hours = Math.floor(normalised / 60);
  const mins = normalised % 60;
  return `${String(hours).padStart(2, "0")}:${String(mins).padStart(2, "0")}`;
}

/**
 * Validate a class slot against the 09:00 - 17:00 policy.
 * Returns a human readable message for the first violation found.
 */
export function validateAcademicWindow(startTime: string, endTime: string): WindowValidation {
  const start = toMinutes(startTime);
  const end = toMinutes(endTime);

  if (start === null || end === null) {
    return { valid: false, message: "Enter both a start and an end time in HH:MM format." };
  }
  if (end <= start) {
    return { valid: false, message: "End time must be later than start time." };
  }

  const dayStart = toMinutes(ACADEMIC_DAY_START) ?? 0;
  const dayEnd = toMinutes(ACADEMIC_DAY_END) ?? 0;

  if (start < dayStart) {
    return {
      valid: false,
      message: `Classes cannot start before ${ACADEMIC_DAY_START}. Official classes run between ${ACADEMIC_DAY_START} and ${ACADEMIC_DAY_END}.`,
    };
  }
  if (end > dayEnd) {
    return {
      valid: false,
      message: `Classes cannot end after ${ACADEMIC_DAY_END}. A class starting at ${startTime} must end by ${ACADEMIC_DAY_END}.`,
    };
  }

  return { valid: true };
}

/** True when two [start, end) windows overlap. */
export function windowsOverlap(
  aStart: string,
  aEnd: string,
  bStart: string,
  bEnd: string
): boolean {
  const a1 = toMinutes(aStart);
  const a2 = toMinutes(aEnd);
  const b1 = toMinutes(bStart);
  const b2 = toMinutes(bEnd);
  if (a1 === null || a2 === null || b1 === null || b2 === null) return false;
  return a1 < b2 && b1 < a2;
}

/** Human readable time window, e.g. "09:00 - 10:00". */
export function formatTimeWindow(startTime?: string | null, endTime?: string | null): string {
  if (!startTime || !endTime) return "—";
  return `${startTime} - ${endTime}`;
}

/** Duration of a slot in minutes (0 when the window is not parsable). */
export function durationMinutes(startTime?: string | null, endTime?: string | null): number {
  if (!startTime || !endTime) return 0;
  const start = toMinutes(startTime);
  const end = toMinutes(endTime);
  if (start === null || end === null) return 0;
  return Math.max(0, end - start);
}

/** Today's calendar date in the browser's local timezone (YYYY-MM-DD). */
export function todayIso(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/** Format an ISO date (YYYY-MM-DD) for display without timezone drift. */
export function formatIsoDate(isoDate: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate);
  if (!match) return isoDate;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date);
}

/** Weekday name of an ISO date without timezone conversion. */
export function weekdayOfIsoDate(isoDate: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate);
  if (!match) return "";
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return date.toLocaleDateString("en-GB", { weekday: "long" });
}

/** ISO date of the Monday of the week containing the given date. */
export function startOfWeekIso(isoDate: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate);
  if (!match) return isoDate;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  const offset = (date.getDay() + 6) % 7; // Monday = 0
  date.setDate(date.getDate() - offset);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/** Add (or subtract) days to an ISO date, returning an ISO date. */
export function addDaysIso(isoDate: string, days: number): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate);
  if (!match) return isoDate;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  date.setDate(date.getDate() + days);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}
