import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import ForgotPasswordPage from "@/components/auth/ForgotPasswordPage"; import ResetPasswordPage from "@/components/auth/ResetPasswordPage"
import { AuthProvider } from "@/context/AuthContext";
import { AppLayout } from "@/components/layout";
import { ErrorBoundary } from "@/components/layout/ErrorBoundary";
import { ProtectedRoute } from "@/components/auth";
import { DashboardView } from "@/features/dashboard";
import { StudentsView } from "@/features/students";
import { AttendanceView } from "@/features/attendance";
import { TimetableView } from "@/features/timetable";
import { SessionsView } from "@/features/sessions";
import { FacultyView } from "@/features/faculty";
import { RoomsView } from "@/features/rooms";
import { ReportsView } from "@/features/reports";
import { AssistantView } from "@/features/assistant";
import { AuditLogView } from "@/features/audit";
import { SettingsView } from "@/features/settings";
import { MyProfileView } from "@/features/settings/MyProfileView";
import { DefaultersView } from "@/features/defaulters";
import { CalendarView } from "@/features/calendar";
import { ExamControlView, InvigilatorFormBView } from "@/features/exams";

/**
 * All pages share one layout route so the shell (sidebar, header, notification
 * polling and scroll container) stays mounted while the user moves between
 * tabs. Only the page body changes.
 */
export function App() {
  return (
    <AuthProvider>
      <ErrorBoundary>
        <BrowserRouter>
          <Routes>
            <Route element={<AppLayout />}>
              <Route path="/login" element={<DashboardView />} />
              <Route
                path="/"
                element={
                  <ProtectedRoute allowedRoles={["ADMIN", "FACULTY", "VIEWER"]} pageTitle="Dashboard">
                    <DashboardView />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/students"
                element={
                  <ProtectedRoute allowedRoles={["ADMIN", "FACULTY", "VIEWER"]} pageTitle="Student Registry">
                    <StudentsView />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/attendance"
                element={
                  <ProtectedRoute allowedRoles={["ADMIN", "FACULTY", "VIEWER"]} pageTitle="Attendance Rosters">
                    <AttendanceView />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/timetable"
                element={
                  <ProtectedRoute allowedRoles={["ADMIN", "FACULTY", "VIEWER"]} pageTitle="Academic Timetable">
                    <TimetableView />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/calendar"
                element={
                  <ProtectedRoute allowedRoles={["ADMIN", "FACULTY", "VIEWER"]} pageTitle="Attendance Calendar & Heatmap">
                    <CalendarView />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/exams"
                element={
                  <ProtectedRoute allowedRoles={["ADMIN", "FACULTY"]} pageTitle="Exam Cell & Form-B Control">
                    <ExamControlView />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/invigilation"
                element={
                  <ProtectedRoute allowedRoles={["ADMIN", "FACULTY"]} pageTitle="Invigilator Form-B Sheet">
                    <InvigilatorFormBView />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/exams/:examId/rooms/:roomNo"
                element={
                  <ProtectedRoute allowedRoles={["ADMIN", "FACULTY"]} pageTitle="Invigilator Form-B Sheet">
                    <InvigilatorFormBView />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/sessions"
                element={
                  <ProtectedRoute allowedRoles={["ADMIN", "FACULTY", "VIEWER"]} pageTitle="Academic Sessions">
                    <SessionsView />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/faculty"
                element={
                  <ProtectedRoute allowedRoles={["ADMIN"]} pageTitle="Admin Command Center">
                    <FacultyView />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/admin"
                element={
                  <ProtectedRoute allowedRoles={["ADMIN"]} pageTitle="Admin Command Center">
                    <FacultyView />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/rooms"
                element={
                  <ProtectedRoute allowedRoles={["ADMIN"]} pageTitle="Rooms & Facilities Management">
                    <RoomsView />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/defaulters"
                element={
                  <ProtectedRoute allowedRoles={["ADMIN", "FACULTY", "VIEWER"]} pageTitle="Attendance Defaulters">
                    <DefaultersView />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/reports"
                element={
                  <ProtectedRoute allowedRoles={["ADMIN", "FACULTY", "VIEWER"]} pageTitle="Reports & Analytics">
                    <ReportsView />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/assistant"
                element={
                  <ProtectedRoute allowedRoles={["ADMIN", "FACULTY", "VIEWER"]} pageTitle="AI Assistant">
                    <AssistantView />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/audit"
                element={
                  <ProtectedRoute allowedRoles={["ADMIN"]} pageTitle="System Audit Logs">
                    <AuditLogView />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/settings"
                element={
                  <ProtectedRoute allowedRoles={["ADMIN", "FACULTY", "VIEWER"]} pageTitle="Settings & Preferences">
                    <SettingsView />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/profile"
                element={
                  <ProtectedRoute allowedRoles={["ADMIN", "FACULTY", "VIEWER"]} pageTitle="My Profile">
                    <MyProfileView />
                  </ProtectedRoute>
                }
              />
            </Route>
            <Route path="/auth/forgot-password" element={<ForgotPasswordPage />} />
            <Route path="/auth/verify-otp" element={<ForgotPasswordPage initialStep="otp" />} />
            <Route path="/auth/reset-password" element={<ResetPasswordPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </ErrorBoundary>
    </AuthProvider>
  );
}

export default App;
