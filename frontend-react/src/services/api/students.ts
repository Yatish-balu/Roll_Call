import { apiClient } from "@/services/api/client";
import { fetchSessions } from "@/services/api/sessions";
import { fetchMetaConfig } from "@/services/api/defaulters";

export interface Student {
  usn: string;
  name: string;
  branch: string;
  semester?: number | null;
  semester_id?: string | null;
  section?: string | null;
  section_id?: string | null;
  batch?: string | null;
  batch_id?: string | null;
  roll_no?: string | null;
  department_id?: string | null;
  dept_id?: string | null;
}

export interface StudentPage {
  items: Student[];
  total: number;
  limit: number;
  offset: number;
}

export interface StudentCreateParams {
  usn: string;
  name: string;
  branch: string;
  department_id?: string;
  semester?: number;
  section?: string;
  batch?: string;
}

export interface RawAttendanceRecord {
  session_id: string;
  usn: string;
  room_id: string;
  status: "PRESENT" | "ABSENT" | "PENDING" | "UNREVIEWED";
  source: string;
  confidence?: number;
}

export interface StudentLedgerEntry {
  session_id: string;
  date: string;
  subject: string;
  room: string;
  status: "PRESENT" | "ABSENT" | "PENDING" | "UNREVIEWED";
  source: string;
  confidence?: number;
}

export interface StudentAttendanceSummary {
  student: Student;
  attended_classes: number;
  conducted_classes: number;
  attendance_percentage: number;
  health_band: "GREEN" | "YELLOW" | "RED";
  health_band_label: string;
  ledger: StudentLedgerEntry[];
}

export async function fetchStudents(params?: {
  limit?: number;
  offset?: number;
  branch?: string;
  semester?: number;
  search?: string;
}): Promise<StudentPage> {
  const queryParams: Record<string, string | number | boolean | undefined | null> = {};
  if (params?.limit) queryParams.limit = params.limit;
  if (params?.offset !== undefined) queryParams.offset = params.offset;
  if (params?.branch && params.branch !== "ALL") queryParams.branch = params.branch;
  if (params?.semester !== undefined && params.semester !== null)
    queryParams.semester = params.semester;
  if (params?.search && params.search.trim()) queryParams.search = params.search.trim();

  return apiClient.get<StudentPage>(
    "/api/v1/students",
    Object.keys(queryParams).length ? queryParams : undefined
  );
}

export async function getStudent(usn: string): Promise<Student> {
  return apiClient.get<Student>(`/api/v1/students/${encodeURIComponent(usn)}`);
}

export async function createStudent(data: StudentCreateParams): Promise<Student> {
  return apiClient.post<Student>("/api/v1/students", data);
}

export async function fetchStudentAttendanceRecords(usn: string): Promise<RawAttendanceRecord[]> {
  return apiClient.get<RawAttendanceRecord[]>(`/api/v1/attendance/students/${encodeURIComponent(usn)}`);
}

export async function fetchStudentAttendanceSummary(usn: string): Promise<StudentAttendanceSummary> {
  const [student, records, sessionsRes, meta] = await Promise.all([
    getStudent(usn),
    fetchStudentAttendanceRecords(usn),
    fetchSessions({ limit: 100 }),
    fetchMetaConfig().catch(() => ({
      attendance_bands: { green_above_percent: 85.0, yellow_from_percent: 70.0 },
    })),
  ]);

  const sessionMap = new Map<string, { date: string; subject: string; room: string }>();
  for (const s of sessionsRes.items || []) {
    sessionMap.set(s.session_id, {
      date: s.date,
      subject: s.subject_code || s.subject || "Session",
      room: s.allocations?.[0]?.room_id || "",
    });
  }

  // Construct ledger in chronological order
  const ledger: StudentLedgerEntry[] = records.map((r) => {
    const sess = sessionMap.get(r.session_id);
    return {
      session_id: r.session_id,
      date: sess?.date || "—",
      subject: sess?.subject || "—",
      room: r.room_id || sess?.room || "—",
      status: r.status,
      source: r.source || "—",
      confidence: r.confidence,
    };
  });

  // Sort chronologically by date
  ledger.sort((a, b) => a.date.localeCompare(b.date));

  const conducted = records.length;
  const attended = records.filter((r) => r.status === "PRESENT").length;
  const percentage = conducted > 0 ? (attended / conducted) * 100 : 0.0;

  const greenThreshold = meta.attendance_bands?.green_above_percent ?? 85.0;
  const yellowThreshold = meta.attendance_bands?.yellow_from_percent ?? 70.0;

  let health_band: "GREEN" | "YELLOW" | "RED" = "GREEN";
  let health_band_label = "Green (>85% - High Attendance)";

  if (percentage > greenThreshold) {
    health_band = "GREEN";
    health_band_label = `Green (>${greenThreshold}% - High Attendance)`;
  } else if (percentage >= yellowThreshold) {
    health_band = "YELLOW";
    health_band_label = `Yellow (${yellowThreshold}–${greenThreshold}% - Moderate Attendance)`;
  } else {
    health_band = "RED";
    health_band_label = `Red (<${yellowThreshold}% - Critical / Defaulter)`;
  }

  return {
    student,
    attended_classes: attended,
    conducted_classes: conducted,
    attendance_percentage: percentage,
    health_band,
    health_band_label,
    ledger,
  };
}
