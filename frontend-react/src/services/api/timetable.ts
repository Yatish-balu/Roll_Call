import { apiClient } from "@/services/api/client";

export interface TimetableEntry {
  entry_id: string;
  timetable_id: string;
  day_of_week: string;
  period_number: number;
  start_time: string;
  end_time: string;
  subject_code: string;
  subject_name?: string | null;
  room_id: string;
  room_name?: string | null;
  faculty_id?: string | null;
  faculty_name?: string | null;
  batch_id?: string | null;
  batch_label?: string | null;
  duration_minutes?: number | null;
}

export interface TimetableDay {
  day_of_week: string;
  date?: string | null;
  entries: TimetableEntry[];
}

export interface TimetableWeek {
  week_start: string;
  days: TimetableDay[];
  total_entries: number;
  timetable_count: number;
  has_timetable: boolean;
  message?: string | null;
}

export interface TimetableReference {
  departments: Array<{ dept_id: string; name: string }>;
  semesters: Array<{
    semester_id: string;
    semester_number: number;
    semester_label: string;
    year_id: string;
  }>;
  academic_years: Array<{ year_id: string; label?: string | null }>;
  sections: Array<{ section_id: string; section_label: string; dept_id: string }>;
  batches: Array<{ batch_id: string; batch_label: string; batch_type: string; section_id: string }>;
  subjects: Array<{ subject_code: string; name: string; subject_type: string; dept_id: string }>;
  rooms: Array<{ room_id: string; name: string; room_type?: string | null; capacity?: number | null }>;
  timetables: Array<{
    timetable_id: string;
    dept_id: string;
    semester_id: string;
    section_id: string;
    year_id: string;
    effective_from: string;
    effective_to?: string | null;
    is_active: number;
  }>;
}

export interface TimetableEntryInput {
  timetable_id: string;
  day_of_week: string;
  period_number: number;
  start_time: string;
  end_time: string;
  subject_code: string;
  room_id: string;
  faculty_id?: string;
  batch_id?: string;
}

export async function fetchTimetableWeek(params?: {
  week_start?: string;
}): Promise<TimetableWeek> {
  return apiClient.get<TimetableWeek>("/api/v1/timetable/week", params);
}

export async function fetchTimetableReference(): Promise<TimetableReference> {
  return apiClient.get<TimetableReference>("/api/v1/timetable/reference");
}

export async function fetchTimetableEntries(params?: {
  timetable_id?: string;
  day_of_week?: string;
}): Promise<TimetableEntry[]> {
  return apiClient.get<TimetableEntry[]>("/api/v1/timetable/entries", params);
}

export async function createTimetableEntry(
  payload: TimetableEntryInput
): Promise<TimetableEntry> {
  return apiClient.post<TimetableEntry>("/api/v1/timetable/entries", payload);
}

export async function updateTimetableEntry(
  entryId: string,
  payload: Partial<TimetableEntryInput>
): Promise<TimetableEntry> {
  return apiClient.put<TimetableEntry>(
    `/api/v1/timetable/entries/${encodeURIComponent(entryId)}`,
    payload
  );
}

export async function deleteTimetableEntry(entryId: string): Promise<void> {
  await apiClient.delete<void>(`/api/v1/timetable/entries/${encodeURIComponent(entryId)}`);
}
