import { Outlet, useLocation } from "react-router-dom";
import { AppShell } from "./AppShell";

/**
 * Single layout route for the whole authenticated app.
 *
 * Keeping `<AppShell>` mounted across tab switches (instead of wrapping every
 * route in its own copy) means the sidebar, header, notification state and the
 * scroll container survive navigation, so visiting a tab no longer remounts the
 * entire chrome and refires the header's requests.
 */
const TITLES: Record<string, string> = {
  "/": "Dashboard",
  "/students": "Students",
  "/attendance": "Attendance",
  "/timetable": "Timetable",
  "/calendar": "Attendance Calendar",
  "/exams": "Exam Cell",
  "/invigilation": "My Invigilation",
  "/sessions": "Sessions",
  "/faculty": "Admin Command Center",
  "/admin": "Admin Command Center",
  "/rooms": "Rooms & Facilities",
  "/defaulters": "Defaulter Registry",
  "/reports": "Reports & Analytics",
  "/assistant": "AI Assistant",
  "/audit": "Audit Logs",
  "/settings": "Settings",
  "/profile": "My Profile",
};

function resolveTitle(pathname: string): string {
  const clean = pathname.replace(/\/+$/, "") || "/";

  // Deep link straight into a Form-B sheet.
  if (/^\/exams\/[^/]+\/rooms\//.test(clean)) {
    return "Form-B Attendance";
  }

  if (TITLES[clean]) {
    return TITLES[clean];
  }

  const prefix = Object.keys(TITLES)
    .filter((path) => path !== "/" && clean.startsWith(`${path}/`))
    .sort((a, b) => b.length - a.length)[0];

  return prefix ? TITLES[prefix] : "Dashboard";
}

export function AppLayout() {
  const { pathname } = useLocation();
  return (
    <AppShell title={resolveTitle(pathname)}>
      <Outlet />
    </AppShell>
  );
}
