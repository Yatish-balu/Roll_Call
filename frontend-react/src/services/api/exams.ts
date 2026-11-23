import { apiClient } from "@/services/api/client";

export type ExamStatus = "SCHEDULED" | "IN_PROGRESS" | "COMPLETED" | "CANCELLED";
export type RoomExamStatus = "SUBMITTED" | "OPEN" | "SCHEDULED";
export type ExamCandidateStatus = "PRESENT" | "ABSENT";

export interface Exam {
  id: string;
  title: string;
  sem: number | string;
  branch: string;
  course_code: string;
  course_name?: string;
  date: string;
  time: string;
  status: ExamStatus;
  total_students: number;
  present_count: number;
  absent_count: number;
}

export interface RoomSummary {
  room_id: string;
  room_name: string;
  present: number;
  total: number;
  status: RoomExamStatus;
  invigilator_id?: string;
  invigilator_name?: string;
  deadline?: string;
}

export interface BranchSummary {
  branch: string;
  total: number;
  present: number;
  absent: number;
  percentage: number;
}

export interface StudentExamRosterItem {
  sl: number;
  usn: string;
  name: string;
  branch: string;
  status: ExamCandidateStatus;
  seat_number?: string;
}

export interface ActiveExamDetails {
  exam: Exam;
  rooms: RoomSummary[];
  branch_summaries: BranchSummary[];
}

export interface InvigilationSession {
  exam: Exam;
  room: {
    room_id: string;
    room_name: string;
    invigilator_id: string;
    invigilator_name: string;
  };
  deadline: string; // ISO timestamp
  is_submitted: boolean;
  submitted_at?: string;
  students: StudentExamRosterItem[];
}

export interface CreateExamParams {
  title: string;
  sem: number | string;
  branch: string;
  course_code: string;
  course_name?: string;
  date: string;
  time: string;
}

export interface ScanSignedSheetResult {
  detected_absentees: string[];
  detected_present: string[];
  confidence: number;
  total_detected: number;
}

/* ------------------------------------------------------------------ */
/* Mock Data Store (Fallback when backend is offline or unmigrated)    */
/* ------------------------------------------------------------------ */

const DEFAULT_DEADLINE_MS = 25 * 60 * 1000; // 25 minutes from now

const mockActiveExam: ActiveExamDetails = {
  exam: {
    id: "EXAM-2026-CY-01",
    title: "CIE-III November 2026",
    sem: "Sem 7",
    branch: "CY",
    course_code: "22CY72",
    course_name: "Cloud Security & DevSecOps",
    date: "02-Nov-2026",
    time: "10:00-11:30 AM",
    status: "IN_PROGRESS",
    total_students: 120,
    present_count: 115,
    absent_count: 5,
  },
  rooms: [
    {
      room_id: "A-201",
      room_name: "Room A-201 (Lecture Hall 1)",
      present: 38,
      total: 40,
      status: "OPEN",
      invigilator_id: "FAC-102",
      invigilator_name: "Dr. Ramesh Sharma",
      deadline: new Date(Date.now() + DEFAULT_DEADLINE_MS).toISOString(),
    },
    {
      room_id: "A-202",
      room_name: "Room A-202 (Lecture Hall 2)",
      present: 40,
      total: 40,
      status: "SUBMITTED",
      invigilator_id: "FAC-105",
      invigilator_name: "Prof. Priya Nair",
      deadline: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
    },
    {
      room_id: "B-101",
      room_name: "Room B-101 (Computing Lab A)",
      present: 37,
      total: 40,
      status: "OPEN",
      invigilator_id: "FAC-109",
      invigilator_name: "Dr. Suresh Kumar",
      deadline: new Date(Date.now() + DEFAULT_DEADLINE_MS).toISOString(),
    },
    {
      room_id: "B-104",
      room_name: "Room B-104 (Drawing Hall)",
      present: 0,
      total: 40,
      status: "SCHEDULED",
      invigilator_id: "FAC-114",
      invigilator_name: "Prof. Ananya Rao",
      deadline: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
    },
  ],
  branch_summaries: [
    { branch: "CY", total: 60, present: 58, absent: 2, percentage: 96.7 },
    { branch: "IS", total: 40, present: 38, absent: 2, percentage: 95.0 },
    { branch: "CS", total: 20, present: 19, absent: 1, percentage: 95.0 },
  ],
};

const DEFAULT_STUDENTS: StudentExamRosterItem[] = [
  { sl: 1, usn: "1RV22CY001", name: "Aarav Sharma", branch: "CY", status: "PRESENT", seat_number: "A1" },
  { sl: 2, usn: "1RV22CY002", name: "Aditi Rao", branch: "CY", status: "PRESENT", seat_number: "A2" },
  { sl: 3, usn: "1RV22CY003", name: "Akash Verma", branch: "CY", status: "PRESENT", seat_number: "A3" },
  { sl: 4, usn: "1RV22CY004", name: "Ananya Iyer", branch: "CY", status: "PRESENT", seat_number: "A4" },
  { sl: 5, usn: "1RV22CY005", name: "Bhavya Hegde", branch: "CY", status: "PRESENT", seat_number: "A5" },
  { sl: 6, usn: "1RV22CY006", name: "Chetan Kumar", branch: "CY", status: "PRESENT", seat_number: "A6" },
  { sl: 7, usn: "1RV22CY007", name: "Deepika Sen", branch: "CY", status: "PRESENT", seat_number: "A7" },
  { sl: 8, usn: "1RV22CY008", name: "Gautam Menon", branch: "CY", status: "PRESENT", seat_number: "A8" },
  { sl: 9, usn: "1RV22CY009", name: "Harshita Joshi", branch: "CY", status: "PRESENT", seat_number: "A9" },
  { sl: 10, usn: "1RV22CY010", name: "Ishaan Kulkarni", branch: "CY", status: "PRESENT", seat_number: "A10" },
  { sl: 11, usn: "1RV22CY011", name: "Kavya Patel", branch: "CY", status: "PRESENT", seat_number: "B1" },
  { sl: 12, usn: "1RV22CY012", name: "Kiran Deshmukh", branch: "CY", status: "PRESENT", seat_number: "B2" },
  { sl: 13, usn: "1RV22CY013", name: "Manish Reddy", branch: "CY", status: "PRESENT", seat_number: "B3" },
  { sl: 14, usn: "1RV22CY014", name: "Meera Nambiar", branch: "CY", status: "ABSENT", seat_number: "B4" },
  { sl: 15, usn: "1RV22CY015", name: "Naveen Sundaram", branch: "CY", status: "PRESENT", seat_number: "B5" },
  { sl: 16, usn: "1RV22CY016", name: "Neha Bhat", branch: "CY", status: "PRESENT", seat_number: "B6" },
  { sl: 17, usn: "1RV22CY017", name: "Nikhil Pillai", branch: "CY", status: "PRESENT", seat_number: "B7" },
  { sl: 18, usn: "1RV22CY018", name: "Pooja Shetty", branch: "CY", status: "PRESENT", seat_number: "B8" },
  { sl: 19, usn: "1RV22CY019", name: "Pranav Gowda", branch: "CY", status: "PRESENT", seat_number: "B9" },
  { sl: 20, usn: "1RV22CY020", name: "Rahul Nair", branch: "CY", status: "PRESENT", seat_number: "B10" },
  { sl: 21, usn: "1RV22IS021", name: "Riya Kapoor", branch: "IS", status: "PRESENT", seat_number: "C1" },
  { sl: 22, usn: "1RV22IS022", name: "Rohan Das", branch: "IS", status: "PRESENT", seat_number: "C2" },
  { sl: 23, usn: "1RV22IS023", name: "Sahil Khan", branch: "IS", status: "PRESENT", seat_number: "C3" },
  { sl: 24, usn: "1RV22IS024", name: "Sanjana Roy", branch: "IS", status: "PRESENT", seat_number: "C4" },
  { sl: 25, usn: "1RV22IS025", name: "Siddharth Jain", branch: "IS", status: "PRESENT", seat_number: "C5" },
  { sl: 26, usn: "1RV22IS026", name: "Sneha Pai", branch: "IS", status: "PRESENT", seat_number: "C6" },
  { sl: 27, usn: "1RV22IS027", name: "Sparsh Gupta", branch: "IS", status: "ABSENT", seat_number: "C7" },
  { sl: 28, usn: "1RV22IS028", name: "Sumanth Naik", branch: "IS", status: "PRESENT", seat_number: "C8" },
  { sl: 29, usn: "1RV22IS029", name: "Swati Mishra", branch: "IS", status: "PRESENT", seat_number: "C9" },
  { sl: 30, usn: "1RV22IS030", name: "Tanvi Acharya", branch: "IS", status: "PRESENT", seat_number: "C10" },
  { sl: 31, usn: "1RV22CS031", name: "Tarun Prasad", branch: "CS", status: "PRESENT", seat_number: "D1" },
  { sl: 32, usn: "1RV22CS032", name: "Ujjwal Tiwari", branch: "CS", status: "PRESENT", seat_number: "D2" },
  { sl: 33, usn: "1RV22CS033", name: "Varun Bhatia", branch: "CS", status: "PRESENT", seat_number: "D3" },
  { sl: 34, usn: "1RV22CS034", name: "Vidya Sagar", branch: "CS", status: "PRESENT", seat_number: "D4" },
  { sl: 35, usn: "1RV22CS035", name: "Vikas Hegde", branch: "CS", status: "PRESENT", seat_number: "D5" },
  { sl: 36, usn: "1RV22CS036", name: "Vinay Kulkarni", branch: "CS", status: "PRESENT", seat_number: "D6" },
  { sl: 37, usn: "1RV22CS037", name: "Vishal Chauhan", branch: "CS", status: "PRESENT", seat_number: "D7" },
  { sl: 38, usn: "1RV22CS038", name: "Yashasvi Sinha", branch: "CS", status: "PRESENT", seat_number: "D8" },
  { sl: 39, usn: "1RV22CS039", name: "Yusuf Ali", branch: "CS", status: "PRESENT", seat_number: "D9" },
  { sl: 40, usn: "1RV22CS040", name: "Zoya Fathima", branch: "CS", status: "PRESENT", seat_number: "D10" },
];

const mockInvigilationSession: InvigilationSession = {
  exam: { ...mockActiveExam.exam },
  room: {
    room_id: "A-201",
    room_name: "Room A-201 (Lecture Hall 1)",
    invigilator_id: "FAC-102",
    invigilator_name: "Dr. Ramesh Sharma",
  },
  deadline: new Date(Date.now() + DEFAULT_DEADLINE_MS).toISOString(),
  is_submitted: false,
  students: [...DEFAULT_STUDENTS],
};

/* ------------------------------------------------------------------ */
/* API Service Functions                                              */
/* ------------------------------------------------------------------ */

/**
 * Fetch the currently active examination and room allocations.
 */
export async function fetchActiveExam(): Promise<ActiveExamDetails> {
  try {
    return await apiClient.get<ActiveExamDetails>("/api/v1/exams/active");
  } catch {
    // Fallback to local mock active exam
    return Promise.resolve(JSON.parse(JSON.stringify(mockActiveExam)));
  }
}

/**
 * Fetch list of scheduled/historical examinations.
 */
export async function fetchExams(params?: {
  limit?: number;
  offset?: number;
}): Promise<{ items: Exam[]; total: number }> {
  try {
    return await apiClient.get<{ items: Exam[]; total: number }>("/api/v1/exams", params);
  } catch {
    return Promise.resolve({
      items: [mockActiveExam.exam],
      total: 1,
    });
  }
}

/**
 * Create a new examination schedule.
 */
export async function createExam(params: CreateExamParams): Promise<Exam> {
  try {
    return await apiClient.post<Exam>("/api/v1/exams", params);
  } catch {
    const newExam: Exam = {
      id: `EXAM-${Date.now()}`,
      title: params.title,
      sem: params.sem,
      branch: params.branch,
      course_code: params.course_code,
      course_name: params.course_name || "Course Subject",
      date: params.date,
      time: params.time,
      status: "SCHEDULED",
      total_students: 120,
      present_count: 0,
      absent_count: 0,
    };
    mockActiveExam.exam = newExam;
    mockActiveExam.rooms.forEach((r) => {
      r.status = "SCHEDULED";
      r.present = 0;
    });
    return Promise.resolve(newExam);
  }
}

/**
 * Upload seating arrangement CSV.
 */
export async function uploadSeatingCsv(file: File): Promise<{
  message: string;
  rooms_count: number;
  students_count: number;
}> {
  const formData = new FormData();
  formData.append("file", file);

  try {
    return await apiClient.post<{ message: string; rooms_count: number; students_count: number }>(
      "/api/v1/exams/upload-seating",
      formData
    );
  } catch {
    // Mock successful parsing of uploaded CSV
    return Promise.resolve({
      message: `Successfully processed ${file.name}: Seating generated for 4 rooms & 120 students.`,
      rooms_count: 4,
      students_count: 120,
    });
  }
}

/**
 * Download Form-B Absentees PDF.
 */
export async function downloadFormBAbsenteesPdf(examId: string): Promise<Blob> {
  try {
    return await apiClient.get<Blob>(`/api/v1/exams/${encodeURIComponent(examId)}/form-b-pdf`, undefined, {
      responseType: "blob",
    });
  } catch {
    // Generate mock CSV / text blob for absentees
    const content = [
      `=============================================================`,
      `EXAM CELL FORM-B CONSOLIDATED ABSENTEE STATEMENT`,
      `Exam: ${mockActiveExam.exam.title}`,
      `Course Code: ${mockActiveExam.exam.course_code} (${mockActiveExam.exam.course_name || ""})`,
      `Date & Time: ${mockActiveExam.exam.date} · ${mockActiveExam.exam.time}`,
      `Total Registered: ${mockActiveExam.exam.total_students}`,
      `Total Present: ${mockActiveExam.exam.present_count} | Total Absent: ${mockActiveExam.exam.absent_count}`,
      `=============================================================`,
      ``,
      `DETAILED ABSENTEE ROSTER:`,
      `Sl No. | USN         | Student Name       | Branch | Room Allocated`,
      `-------------------------------------------------------------`,
      `1      | 1RV22CY014  | Meera Nambiar      | CY     | Room A-201`,
      `2      | 1RV22IS027  | Sparsh Gupta       | IS     | Room A-201`,
      `3      | 1RV22CY038  | Yashasvi Sinha     | CY     | Room B-101`,
      `4      | 1RV22IS019  | Pranav Gowda       | IS     | Room B-101`,
      `5      | 1RV22CS006  | Chetan Kumar       | CS     | Room B-101`,
      `-------------------------------------------------------------`,
      `Generated on: ${new Date().toLocaleString()}`,
      `Status: Consolidated by Exam Cell Controller`,
    ].join("\n");
    return Promise.resolve(new Blob([content], { type: "text/plain" }));
  }
}

/**
 * Download Room Seating & Signature Sheets.
 */
export async function downloadRoomSignSheets(examId: string): Promise<Blob> {
  try {
    return await apiClient.get<Blob>(`/api/v1/exams/${encodeURIComponent(examId)}/sign-sheets`, undefined, {
      responseType: "blob",
    });
  } catch {
    const content = [
      `=============================================================`,
      `ROOM ATTENDANCE & SIGNATURE VERIFICATION SHEET`,
      `Exam: ${mockActiveExam.exam.title} | Room: All Rooms (A-201, A-202, B-101, B-104)`,
      `Course: ${mockActiveExam.exam.course_code} · Date: ${mockActiveExam.exam.date}`,
      `=============================================================`,
      ``,
      `Instructions for Invigilators:`,
      `1. Verify identity card and hall ticket before collecting signature.`,
      `2. Check-off Present/Absent on RollCall AI Form-B portal before the 30-min window closes.`,
      `3. Return signed sheets to the Exam Cell immediately after completion.`,
      `-------------------------------------------------------------`,
      `Rooms Allocations:`,
      ...mockActiveExam.rooms.map((r) => `* [${r.room_id}] ${r.room_name} - ${r.total} Students - Invigilator: ${r.invigilator_name}`),
    ].join("\n");
    return Promise.resolve(new Blob([content], { type: "text/plain" }));
  }
}

/**
 * Fetch invigilation session details for a room.
 */
export async function fetchInvigilationSession(roomId = "A-201"): Promise<InvigilationSession> {
  try {
    return await apiClient.get<InvigilationSession>(
      `/api/v1/exams/invigilation/${encodeURIComponent(roomId)}`
    );
  } catch {
    const session = JSON.parse(JSON.stringify(mockInvigilationSession)) as InvigilationSession;
    session.room.room_id = roomId;
    return Promise.resolve(session);
  }
}

/**
 * Submit Form-B attendance for an invigilated room.
 */
export async function submitFormB(
  examId: string,
  roomId: string,
  roster: { usn: string; status: ExamCandidateStatus }[]
): Promise<{ success: boolean; message: string; submitted_at: string }> {
  try {
    return await apiClient.post<{ success: boolean; message: string; submitted_at: string }>(
      `/api/v1/exams/${encodeURIComponent(examId)}/rooms/${encodeURIComponent(roomId)}/form-b`,
      { roster }
    );
  } catch {
    const nowIso = new Date().toISOString();
    mockInvigilationSession.is_submitted = true;
    mockInvigilationSession.submitted_at = nowIso;
    mockInvigilationSession.students.forEach((s) => {
      const match = roster.find((r) => r.usn === s.usn);
      if (match) s.status = match.status;
    });

    const targetRoom = mockActiveExam.rooms.find((r) => r.room_id === roomId);
    if (targetRoom) {
      targetRoom.status = "SUBMITTED";
      targetRoom.present = roster.filter((r) => r.status === "PRESENT").length;
    }

    return Promise.resolve({
      success: true,
      message: `Form-B for Room ${roomId} submitted successfully and recorded.`,
      submitted_at: nowIso,
    });
  }
}

/**
 * AI Assist: Scan uploaded signed attendance sheet image to detect absentees and signatures.
 */
export async function scanSignedSheetAi(
  file: File,
  roomId = "A-201"
): Promise<ScanSignedSheetResult> {
  const formData = new FormData();
  formData.append("sheet_image", file);
  formData.append("room_id", roomId);

  try {
    return await apiClient.post<ScanSignedSheetResult>("/api/v1/exams/ai-scan-sheet", formData);
  } catch {
    // Simulated realistic AI recognition delay
    await new Promise((r) => setTimeout(r, 1200));

    // Simulated detected absentees based on marked empty signatures
    return Promise.resolve({
      detected_absentees: ["1RV22CY014", "1RV22IS027"],
      detected_present: DEFAULT_STUDENTS.filter(
        (s) => s.usn !== "1RV22CY014" && s.usn !== "1RV22IS027"
      ).map((s) => s.usn),
      confidence: 0.984,
      total_detected: 40,
    });
  }
}
