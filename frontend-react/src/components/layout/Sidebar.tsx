import React, { useCallback, useMemo } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useBackendHealth } from "@/hooks/useBackendHealth";
import { useAuth } from "@/hooks/useAuth";
import { usePreference } from "@/lib/preferences";

interface NavItem {
  name: string;
  href: string;
  icon: React.ReactNode;
  badge?: string;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

interface SidebarProps {
  isOpen?: boolean;
  onClose?: () => void;
}

/* ------------------------------------------------------------------ */
/* Icons                                                               */
/* ------------------------------------------------------------------ */

const ICONS = {
  home: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
    </svg>
  ),
  attendance: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
    </svg>
  ),
  timetable: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
    </svg>
  ),
  sessions: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  ),
  students: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
    </svg>
  ),
  ai: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
    </svg>
  ),
  reports: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
    </svg>
  ),
  warning: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
    </svg>
  ),
  calendar: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
    </svg>
  ),
  profile: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM15 11a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  ),
  settings: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37a1.724 1.724 0 002.572-1.065z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  ),
  building: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
    </svg>
  ),
  room: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M3 10h18M3 14h18m-9-4v8m-7 4h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
    </svg>
  ),
  audit: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M9 12h6m-6 4h6m-9 4h6m-6-4h6m-6-5h6a2 2 0 012-2v-2a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
    </svg>
  ),
  logout: (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
    </svg>
  ),
  chevron: (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
    </svg>
  ),
  chevronLeft: (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
    </svg>
  ),
  close: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
    </svg>
  ),
};

/* ------------------------------------------------------------------ */
/* Component                                                           */
/* ------------------------------------------------------------------ */

export function Sidebar({ isOpen = false, onClose }: SidebarProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const pathname = location.pathname;
  const { isOnline } = useBackendHealth();
  const { logout, session, isAdmin } = useAuth();
  const [collapsed, setCollapsed] = usePreference("sidebarCollapsed");

  const isLinkActive = useCallback(
    (href: string) => {
      if (href === "/") return pathname === "/";
      return pathname === href || pathname.startsWith(`${href}/`);
    },
    [pathname]
  );

  const groups = useMemo<NavGroup[]>(() => {
    const core: NavGroup = {
      label: "Core Teaching",
      items: [
        { name: "Dashboard", href: "/", icon: ICONS.home },
        { name: "Attendance", href: "/attendance", icon: ICONS.attendance },
        { name: "Timetable", href: "/timetable", icon: ICONS.timetable },
        { name: "Sessions", href: "/sessions", icon: ICONS.sessions },
        { name: "Students", href: "/students", icon: ICONS.students },
      ],
    };

    const intelligence: NavGroup = {
      label: "Intelligence & Analytics",
      items: [
        { name: "AI Assistant", href: "/assistant", icon: ICONS.ai, badge: "AI" },
        { name: "Reports", href: "/reports", icon: ICONS.reports },
        { name: "Defaulters", href: "/defaulters", icon: ICONS.warning },
        { name: "Calendar", href: "/calendar", icon: ICONS.calendar },
      ],
    };

    const account: NavGroup = {
      label: "Account",
      items: [
        { name: "My Profile", href: "/profile", icon: ICONS.profile },
        { name: "Settings", href: "/settings", icon: ICONS.settings },
      ],
    };

    const groups: NavGroup[] = [core, intelligence, account];

    if (isAdmin) {
      groups.push({
        label: "Administration",
        items: [
          { name: "Faculty & Depts", href: "/faculty", icon: ICONS.building, badge: "Admin" },
          { name: "Rooms", href: "/rooms", icon: ICONS.room, badge: "Admin" },
          { name: "Audit Logs", href: "/audit", icon: ICONS.audit, badge: "Admin" },
        ],
      });
    }

    return groups;
  }, [isAdmin]);

  const displayName = session?.name || session?.userId || "User";
  const userInitial = displayName.charAt(0).toUpperCase();
  const roleLabel = isAdmin ? "ADMIN" : session?.role || "FACULTY";

  const handleSignOut = async () => {
    await logout();
    navigate("/login");
  };

  const renderContent = (compact: boolean) => (
    <div className="flex h-full flex-col bg-[#3F451F] text-[#EDE8D8]">
      {/* Brand */}
      <div
        className={`flex items-center gap-3 px-4 pt-5 pb-4 ${
          compact ? "justify-center px-2" : ""
        }`}
      >
        <div className="h-10 w-10 shrink-0 rounded-xl bg-[#EDE8D8]/10 ring-1 ring-[#EDE8D8]/15 flex items-center justify-center">
          <svg className="h-6 w-6 text-[#EDE8D8]" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 3L1 9l4 2.18v6L12 21l7-3.82v-6l2-1.09V17h2V9L12 3zm6.82 6L12 12.72 5.18 9 12 5.28 18.82 9zM17 15.99l-5 2.73-5-2.73v-3.72L12 15l5-2.73v3.72z" />
          </svg>
        </div>
        {!compact && (
          <div className="min-w-0">
            <p className="truncate text-base font-extrabold tracking-tight text-[#FBF8F0]">
              RollCall AI
            </p>
            <p className="truncate text-[11px] text-[#A9AE8C]">Attendance, Simplified</p>
          </div>
        )}
        {compact && (
          <button
            type="button"
            onClick={() => setCollapsed(false)}
            title="Expand sidebar"
            aria-label="Expand sidebar"
            className="ml-auto rounded-lg p-1.5 text-[#A9AE8C] hover:bg-[#EDE8D8]/10 hover:text-[#EDE8D8] transition-colors cursor-pointer"
          >
            {ICONS.chevron}
          </button>
        )}
      </div>

      {/* Workspace badge */}
      {!compact && (
        <div className="px-4 pb-4">
          <div className="flex items-center justify-between gap-2 rounded-xl bg-[#2C3117] px-3 py-2 ring-1 ring-[#EDE8D8]/10">
            <span className="flex items-center gap-2 text-xs font-semibold text-[#E4E0CB]">
              <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_0_3px_rgba(52,211,153,0.18)]" />
              Teacher Workspace
            </span>
            <span className="rounded-md bg-[#EDE8D8]/10 px-1.5 py-0.5 text-[10px] font-black tracking-wider text-[#A9AE8C]">
              {roleLabel}
            </span>
          </div>
        </div>
      )}

      {/* Navigation */}
      <nav
        aria-label="Primary"
        className={`flex-1 overflow-y-auto pb-4 ${compact ? "px-2" : "px-3"}`}
      >
        {groups.map((group) => (
          <div key={group.label} className="mb-5 last:mb-0">
            {!compact && (
              <p className="px-3 pb-2 text-[10px] font-black uppercase tracking-[0.14em] text-[#8C926F]">
                {group.label}
              </p>
            )}
            <ul className="space-y-1">
              {group.items.map((item) => {
                const active = isLinkActive(item.href);
                return (
                  <li key={item.href}>
                    <Link
                      to={item.href}
                      onClick={() => {
                        if (onClose) onClose();
                      }}
                      title={compact ? item.name : undefined}
                      aria-current={active ? "page" : undefined}
                      className={`group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold transition-all duration-150 ${
                        compact ? "justify-center px-0" : ""
                      } ${
                        active
                          ? "bg-[#A77A13] text-[#FBF8F0] shadow-[0_2px_10px_rgba(167,122,19,0.35)]"
                          : "text-[#DCDCC6] hover:bg-[#EDE8D8]/10 hover:text-[#FBF8F0]"
                      }`}
                    >
                      <span
                        className={`shrink-0 transition-colors ${
                          active ? "text-[#FBF8F0]" : "text-[#A9AE8C] group-hover:text-[#EDE8D8]"
                        }`}
                      >
                        {item.icon}
                      </span>
                      {!compact && <span className="truncate">{item.name}</span>}
                      {!compact && item.badge && (
                        <span
                          className={`ml-auto rounded-md px-1.5 py-0.5 text-[10px] font-black tracking-wide ${
                            active
                              ? "bg-black/20 text-[#FBF8F0]"
                              : "bg-[#EDE8D8]/10 text-[#A9AE8C]"
                          }`}
                        >
                          {item.badge}
                        </span>
                      )}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      {/* Connection status */}
      <div className={`border-t border-[#EDE8D8]/10 ${compact ? "px-2 py-3" : "px-4 py-3"}`}>
        <div
          className={`flex items-center justify-between gap-2 rounded-xl bg-[#2C3117] px-3 py-2 ring-1 ring-[#EDE8D8]/10 ${
            compact ? "justify-center px-2" : ""
          }`}
          title={isOnline ? "Backend connected" : "Backend unreachable"}
        >
          {!compact && (
            <span className="flex items-center gap-2 text-[11px] font-semibold text-[#DCDCC6]">
              <span
                className={`h-2 w-2 rounded-full ${
                  isOnline ? "bg-emerald-400" : "bg-rose-400"
                }`}
              />
              {isOnline ? "Backend Connected" : "Backend Offline"}
            </span>
          )}
          {!compact && (
            <span className="font-mono text-[10px] text-[#8C926F]">:8000</span>
          )}
        </div>
      </div>

      {/* Account */}
      <div className={`border-t border-[#EDE8D8]/10 ${compact ? "px-2 py-3" : "px-3 py-3"}`}>
        <div
          className={`flex items-center gap-3 rounded-xl bg-[#2C3117] px-3 py-2 ring-1 ring-[#EDE8D8]/10 ${
            compact ? "justify-center px-2" : ""
          }`}
        >
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#EDE8D8] text-sm font-black text-[#3F451F]">
            {userInitial}
          </div>
          {!compact && (
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-bold text-[#FBF8F0]">{displayName}</p>
              <p className="truncate font-mono text-[10px] text-[#8C926F]">
                {session?.userId || "—"}
              </p>
            </div>
          )}
          <div className="flex items-center gap-1">
              <Link
                to="/settings"
                title="Settings"
                aria-label="Settings"
                className="rounded-lg p-1.5 text-[#A9AE8C] transition-colors hover:bg-[#EDE8D8]/10 hover:text-[#FBF8F0]"
              >
                {ICONS.settings}
              </Link>
              <button
                type="button"
                onClick={() => void handleSignOut()}
                title="Sign out"
                aria-label="Sign out"
                className="rounded-lg p-1.5 text-[#A9AE8C] transition-colors hover:bg-rose-500/20 hover:text-rose-200 cursor-pointer"
              >
                {ICONS.logout}
              </button>
            </div>
        </div>
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop persistent sidebar */}
      <aside
        className={`hidden lg:flex fixed inset-y-0 left-0 z-30 flex-col shadow-2xl transition-[width] duration-200 ${
          collapsed ? "w-[76px]" : "w-64"
        }`}
      >
        {renderContent(collapsed)}
        {!collapsed && (
          <button
            type="button"
            onClick={() => setCollapsed(true)}
            title="Collapse sidebar"
            aria-label="Collapse sidebar"
            className="absolute -right-3 top-24 hidden h-7 w-7 items-center justify-center rounded-full bg-[#FBF8F0] text-[#3F451F] shadow-md ring-1 ring-[#E4DDCA] transition-colors hover:bg-[#EDE8D8] cursor-pointer lg:flex"
          >
            {ICONS.chevronLeft}
          </button>
        )}
      </aside>

      {/* Mobile drawer */}
      {isOpen && (
        <div className="fixed inset-0 z-40 lg:hidden flex">
          <button
            type="button"
            aria-label="Close navigation"
            onClick={onClose}
            className="fixed inset-0 bg-black/50 backdrop-blur-[2px] cursor-pointer"
          />
          <div className="relative flex-1 flex flex-col max-w-[280px] w-full z-50 shadow-2xl">
            {renderContent(false)}
            <button
              type="button"
              onClick={onClose}
              aria-label="Close navigation"
              className="absolute right-3 top-5 rounded-lg p-1.5 text-[#A9AE8C] hover:bg-[#EDE8D8]/10 hover:text-[#EDE8D8] cursor-pointer"
            >
              {ICONS.close}
            </button>
          </div>
        </div>
      )}

      {/* Desktop layout spacer */}
      <div
        className={`hidden lg:block shrink-0 transition-[width] duration-200 ${
          collapsed ? "w-[76px]" : "w-64"
        }`}
      />
    </>
  );
}
