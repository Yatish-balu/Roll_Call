import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "@/context/AuthContext";
import { AppShell } from "@/components/layout";
import { ProtectedRoute, LoginView } from "@/components/auth";
import { DashboardView } from "@/features/dashboard";
import { StudentsView } from "@/features/students";
import { AttendanceView } from "@/features/attendance";
import { TimetableView } from "@/features/timetable";
import { SessionsView } from "@/features/sessions";
import { FacultyView } from "@/features/faculty";
import { RoomsView } from "@/features/rooms";
import { ReportsView } from "@/features/reports";
import { AssistantView } from "@/features/assistant";
import { SettingsView } from "@/features/settings";

export function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginView />} />
          <Route
            path="/"
            element={
              <AppShell title="Dashboard">
                <ProtectedRoute allowedRoles={["ADMIN", "FACULTY", "VIEWER"]} pageTitle="Dashboard">
                  <DashboardView />
                </ProtectedRoute>
              </AppShell>
            }
          />
          <Route
            path="/students"
            element={
              <AppShell title="Students">
                <ProtectedRoute allowedRoles={["ADMIN", "FACULTY", "VIEWER"]} pageTitle="Student Registry">
                  <StudentsView />
                </ProtectedRoute>
              </AppShell>
            }
          />
          <Route
            path="/attendance"
            element={
              <AppShell title="Attendance">
                <ProtectedRoute allowedRoles={["ADMIN", "FACULTY", "VIEWER"]} pageTitle="Attendance Rosters">
                  <AttendanceView />
                </ProtectedRoute>
              </AppShell>
            }
          />
          <Route
            path="/timetable"
            element={
              <AppShell title="Timetable">
                <ProtectedRoute allowedRoles={["ADMIN", "FACULTY", "VIEWER"]} pageTitle="Academic Timetable">
                  <TimetableView />
                </ProtectedRoute>
              </AppShell>
            }
          />
          <Route
            path="/sessions"
            element={
              <AppShell title="Sessions">
                <ProtectedRoute allowedRoles={["ADMIN", "FACULTY", "VIEWER"]} pageTitle="Academic Sessions">
                  <SessionsView />
                </ProtectedRoute>
              </AppShell>
            }
          />
          <Route
            path="/faculty"
            element={
              <AppShell title="Faculty & Departments">
                <ProtectedRoute allowedRoles={["ADMIN"]} pageTitle="Faculty & Department Management">
                  <FacultyView />
                </ProtectedRoute>
              </AppShell>
            }
          />
          <Route
            path="/rooms"
            element={
              <AppShell title="Rooms & Facilities">
                <ProtectedRoute allowedRoles={["ADMIN"]} pageTitle="Rooms & Facilities Management">
                  <RoomsView />
                </ProtectedRoute>
              </AppShell>
            }
          />
          <Route
            path="/reports"
            element={
              <AppShell title="Reports & Analytics">
                <ProtectedRoute allowedRoles={["ADMIN", "FACULTY", "VIEWER"]} pageTitle="Reports & Analytics">
                  <ReportsView />
                </ProtectedRoute>
              </AppShell>
            }
          />
          <Route
            path="/assistant"
            element={
              <AppShell title="AI Assistant">
                <ProtectedRoute allowedRoles={["ADMIN", "FACULTY", "VIEWER"]} pageTitle="AI Assistant">
                  <AssistantView />
                </ProtectedRoute>
              </AppShell>
            }
          />
          <Route
            path="/settings"
            element={
              <AppShell title="Settings">
                <ProtectedRoute allowedRoles={["ADMIN", "FACULTY", "VIEWER"]} pageTitle="Settings & Preferences">
                  <SettingsView />
                </ProtectedRoute>
              </AppShell>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
