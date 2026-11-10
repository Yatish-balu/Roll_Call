import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "@/context/AuthContext";
import { AppShell } from "@/components/layout";
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
          <Route
            path="/login"
            element={
              <AppShell title="Sign In">
                <DashboardView />
              </AppShell>
            }
          />
          <Route
            path="/"
            element={
              <AppShell title="Dashboard">
                <DashboardView />
              </AppShell>
            }
          />
          <Route
            path="/students"
            element={
              <AppShell title="Students">
                <StudentsView />
              </AppShell>
            }
          />
          <Route
            path="/attendance"
            element={
              <AppShell title="Attendance">
                <AttendanceView />
              </AppShell>
            }
          />
          <Route
            path="/timetable"
            element={
              <AppShell title="Timetable">
                <TimetableView />
              </AppShell>
            }
          />
          <Route
            path="/sessions"
            element={
              <AppShell title="Sessions">
                <SessionsView />
              </AppShell>
            }
          />
          <Route
            path="/faculty"
            element={
              <AppShell title="Faculty & Departments">
                <FacultyView />
              </AppShell>
            }
          />
          <Route
            path="/rooms"
            element={
              <AppShell title="Rooms & Facilities">
                <RoomsView />
              </AppShell>
            }
          />
          <Route
            path="/reports"
            element={
              <AppShell title="Reports & Analytics">
                <ReportsView />
              </AppShell>
            }
          />
          <Route
            path="/assistant"
            element={
              <AppShell title="AI Assistant">
                <AssistantView />
              </AppShell>
            }
          />
          <Route
            path="/settings"
            element={
              <AppShell title="Settings">
                <SettingsView />
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

