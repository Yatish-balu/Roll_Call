import React, { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useBackendHealth } from "@/hooks/useBackendHealth";
import { useAuth } from "@/hooks/useAuth";

interface NavItem {
  name: string;
  href: string;
  icon: React.ReactNode;
  badge?: string;
}

interface SidebarProps {
  isOpen?: boolean;
  onClose?: () => void;
}

export function Sidebar({ isOpen = false, onClose }: SidebarProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const pathname = location.pathname;
  const { isOnline } = useBackendHealth();
  const { logout, login, session, isAdmin } = useAuth();
  const [showSwitchModal, setShowSwitchModal] = useState(false);
  const [isSwitching, setIsSwitching] = useState(false);

  const isLinkActive = (href: string) => {
    if (href === "/") {
      return pathname === "/";
    }
    return pathname.startsWith(href);
  };

  // Dedicated navigation for Faculty / Teachers
  const teacherNav: { group: string; items: NavItem[] }[] = [
    {
      group: "Core Teaching",
      items: [
        {
          name: "Dashboard",
          href: "/",
          icon: (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
            </svg>
          ),
        },
        {
          name: "Attendance",
          href: "/attendance",
          icon: (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
            </svg>
          ),
        },
        {
          name: "Timetable",
          href: "/timetable",
          icon: (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
          ),
        },
        {
          name: "Sessions",
          href: "/sessions",
          icon: (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          ),
        },
        {
          name: "Students",
          href: "/students",
          icon: (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
            </svg>
          ),
        },
      ],
    },
    {
      group: "Intelligence & Analytics",
      items: [
        {
          name: "AI Assistant",
          href: "/assistant",
          badge: "AI",
          icon: (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
            </svg>
          ),
        },
        {
          name: "Reports",
          href: "/reports",
          icon: (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
          ),
        },
      ],
    },
  ];

  // Dedicated navigation for Institutional Admin
  const adminNav: { group: string; items: NavItem[] }[] = [
    {
      group: "Administration Center",
      items: [
        {
          name: "Dashboard",
          href: "/",
          icon: (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
            </svg>
          ),
        },
        {
          name: "Faculty & Depts",
          href: "/faculty",
          badge: "Admin",
          icon: (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
            </svg>
          ),
        },
        {
          name: "Rooms",
          href: "/rooms",
          badge: "Admin",
          icon: (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h18M3 14h18m-9-4v8m-7 4h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
          ),
        },
        {
          name: "Sessions",
          href: "/sessions",
          icon: (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          ),
        },
        {
          name: "Timetable",
          href: "/timetable",
          icon: (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
          ),
        },
        {
          name: "Students",
          href: "/students",
          icon: (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
            </svg>
          ),
        },
      ],
    },
    {
      group: "Institutional Insights",
      items: [
        {
          name: "AI Assistant",
          href: "/assistant",
          badge: "AI",
          icon: (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
            </svg>
          ),
        },
        {
          name: "Reports",
          href: "/reports",
          icon: (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
          ),
        },
      ],
    },
  ];

  const currentNavGroups = isAdmin ? adminNav : teacherNav;
  const userInitial = (session?.name || session?.userId || "T").charAt(0).toUpperCase();

  const handleSwitchToAdmin = async () => {
    setIsSwitching(true);
    try {
      await login({ userId: "admin_root", password: "AdminSecurePass_2026!", rememberMe: true });
      setShowSwitchModal(false);
      navigate("/");
    } catch {
      navigate("/login");
    } finally {
      setIsSwitching(false);
    }
  };

  const handleSwitchToTeacher = async () => {
    setIsSwitching(true);
    try {
      await login({ userId: "faculty_ml", password: "FacultyPass_ML_2026!", rememberMe: true });
      setShowSwitchModal(false);
      navigate("/");
    } catch {
      navigate("/login");
    } finally {
      setIsSwitching(false);
    }
  };

  const sidebarContent = (
    <div className="flex flex-col h-full bg-[#3F451F] text-[#EDE8D8] select-none relative overflow-hidden">
      {/* Brand & Portal Header */}
      <div className="p-5 pb-4 border-b border-[#EDE8D8]/10 space-y-3">
        <div className="flex items-center space-x-3">
          <div className="w-10 h-10 rounded-xl bg-[#EDE8D8]/15 flex items-center justify-center text-[#EDE8D8] shadow-sm border border-[#EDE8D8]/10">
            <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 3L1 9l4 2.18v6L12 21l7-3.82v-6l2-1.09V17h2V9L12 3zm6.82 6L12 12.72 5.18 9 12 5.28 18.82 9zM17 15.99l-5 2.73-5-2.73v-3.72L12 15l5-2.73v3.72z" />
            </svg>
          </div>
          <div>
            <h1 className="text-base font-bold tracking-tight text-[#EDE8D8] leading-tight">
              RollCall AI
            </h1>
            <p className="text-[11px] text-[#A3A98F] font-medium leading-tight mt-0.5">
              Attendance, Simplified
            </p>
          </div>
        </div>

        {/* Dynamic Role Badge & Portal Switcher */}
        <div className="flex items-center justify-between px-3 py-1.5 rounded-lg bg-[#2D3216] border border-[#EDE8D8]/10 text-xs">
          <span className="text-[11px] font-bold text-[#D0C6A5] flex items-center space-x-1.5">
            <span className={`w-2 h-2 rounded-full ${isAdmin ? "bg-amber-400" : "bg-emerald-400"}`} />
            <span>{isAdmin ? "Admin Portal" : "Teacher Workspace"}</span>
          </span>
          <button
            type="button"
            onClick={() => setShowSwitchModal(true)}
            title={isAdmin ? "Switch to Teacher View" : "Open Admin Portal"}
            className="text-[10px] font-bold text-amber-300 hover:text-amber-200 underline cursor-pointer"
          >
            {isAdmin ? "Switch Role" : "Admin Portal →"}
          </button>
        </div>
      </div>

      {/* Navigation Groups */}
      <div className="flex-1 py-3 px-3 space-y-4 overflow-y-auto z-10 scrollbar-thin">
        {currentNavGroups.map((group) => (
          <div key={group.group} className="space-y-1">
            <p className="px-3 text-[10px] font-bold tracking-wider text-[#A3A98F] uppercase opacity-80">
              {group.group}
            </p>
            <nav className="space-y-1 pt-1">
              {group.items.map((item) => {
                const isActive = isLinkActive(item.href);
                return (
                  <Link
                    key={item.name}
                    to={item.href}
                    onClick={onClose}
                    className={`flex items-center justify-between px-3.5 py-2.5 rounded-xl text-xs sm:text-sm font-semibold transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#EDE8D8] ${
                      isActive
                        ? "bg-[#A77A13] text-white shadow-md font-bold"
                        : "text-[#EDE8D8]/80 hover:text-[#EDE8D8] hover:bg-[#EDE8D8]/10"
                    }`}
                  >
                    <div className="flex items-center space-x-3 min-w-0">
                      <span className={isActive ? "text-white" : "text-[#EDE8D8]/70"}>
                        {item.icon}
                      </span>
                      <span className="truncate">{item.name}</span>
                    </div>
                    {item.badge && (
                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-md ${
                        isActive
                          ? "bg-black/25 text-white"
                          : "bg-[#2D3216] text-[#D0C6A5]"
                      }`}>
                        {item.badge}
                      </span>
                    )}
                  </Link>
                );
              })}
            </nav>
          </div>
        ))}

        {/* Quick Admin Portal Button for Teachers */}
        {!isAdmin && (
          <div className="pt-2 px-1">
            <button
              type="button"
              onClick={() => setShowSwitchModal(true)}
              className="w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-xs font-bold text-amber-200 bg-[#2D3216]/80 hover:bg-[#2D3216] border border-amber-400/25 transition-all cursor-pointer shadow-2xs"
            >
              <div className="flex items-center space-x-2.5">
                <svg className="w-4 h-4 text-amber-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
                </svg>
                <span>Where is Admin Portal?</span>
              </div>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-400/20 text-amber-200">
                Click here
              </span>
            </button>
          </div>
        )}
      </div>

      {/* User Card & Footer */}
      <div className="p-3 border-t border-[#EDE8D8]/10 z-10 bg-[#3F451F]/95 space-y-2">
        {/* Backend Online status */}
        <div className="flex items-center justify-between px-2.5 py-1 rounded-lg bg-[#2D3216]/60 text-xs">
          <div className="flex items-center space-x-2">
            <span className={`w-2 h-2 rounded-full ${isOnline ? "bg-emerald-400 animate-pulse" : "bg-amber-400"}`} />
            <span className="text-[11px] font-medium text-[#EDE8D8]/90">
              {isOnline ? "Backend Connected" : "Connecting..."}
            </span>
          </div>
          <span className="text-[10px] font-mono text-[#EDE8D8]/60">:8000</span>
        </div>

        {/* User Mini Profile Card */}
        <div className="p-2.5 rounded-xl bg-[#2D3216] border border-[#EDE8D8]/10 flex items-center justify-between">
          <div className="flex items-center space-x-2.5 min-w-0">
            <div className="w-8 h-8 rounded-full bg-[#3F451F] text-[#EDE8D8] border border-[#EDE8D8]/20 flex items-center justify-center font-bold text-xs shrink-0">
              {userInitial}
            </div>
            <div className="min-w-0">
              <p className="text-xs font-bold text-[#EDE8D8] truncate">
                {session?.name || session?.userId || "Faculty"}
              </p>
              <p className="text-[10px] text-[#A3A98F] truncate font-mono">
                {session?.userId || "faculty_ds"}
              </p>
            </div>
          </div>

          <div className="flex items-center space-x-1">
            <Link
              to="/settings"
              onClick={onClose}
              title="Settings"
              className="p-1.5 rounded-lg text-[#EDE8D8]/80 hover:text-white hover:bg-[#EDE8D8]/15 transition-colors"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            </Link>

            <button
              onClick={async () => {
                await logout();
                if (onClose) onClose();
                navigate("/login");
              }}
              title="Sign Out"
              className="p-1.5 rounded-lg text-rose-300 hover:text-rose-100 hover:bg-rose-500/20 transition-colors cursor-pointer"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
              </svg>
            </button>
          </div>
        </div>
      </div>

      {/* Switch Portal Modal */}
      {showSwitchModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="bg-[#FBF8F0] text-[#24251C] rounded-2xl border border-[#E4DDCA] shadow-2xl max-w-md w-full p-6 space-y-4 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center space-x-3">
              <div className="w-10 h-10 rounded-xl bg-[#6C5119]/10 text-[#6C5119] flex items-center justify-center">
                <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
                </svg>
              </div>
              <div>
                <h3 className="text-lg font-extrabold text-[#24251C]">
                  {isAdmin ? "Switch to Teacher Workspace" : "Access Admin Portal"}
                </h3>
                <p className="text-xs text-[#77735F]">
                  Current account: <span className="font-mono font-bold text-[#24251C]">{session?.userId || "faculty.ml"}</span> ({session?.role || "FACULTY"})
                </p>
              </div>
            </div>

            <div className="p-3.5 rounded-xl bg-[#EDE8D8]/50 border border-[#E4DDCA] text-xs text-[#24251C] space-y-2">
              <p className="font-semibold">
                {isAdmin
                  ? "Switch to the Teacher Workspace to take attendance, view individual schedules, and manage assigned batches."
                  : "The Admin Portal contains institutional administration features:"}
              </p>
              {!isAdmin && (
                <ul className="list-disc list-inside space-y-1 text-[#77735F] text-[11px]">
                  <li><strong className="text-[#24251C]">Faculty & Depts:</strong> Manage teachers & assigned subjects</li>
                  <li><strong className="text-[#24251C]">Rooms:</strong> Add and monitor classrooms & laboratories</li>
                  <li><strong className="text-[#24251C]">Master Registry:</strong> Institutional students and timetable</li>
                  <li><strong className="text-[#24251C]">Admin Privileges:</strong> Root configuration & reports</li>
                </ul>
              )}
            </div>

            <div className="flex flex-col sm:flex-row gap-2 pt-2">
              <button
                type="button"
                disabled={isSwitching}
                onClick={isAdmin ? handleSwitchToTeacher : handleSwitchToAdmin}
                className="flex-1 py-2.5 px-4 rounded-xl bg-[#6C5119] hover:bg-[#543F14] text-white text-xs font-bold transition-all shadow-sm cursor-pointer disabled:opacity-50 text-center"
              >
                {isSwitching
                  ? "Authenticating..."
                  : isAdmin
                  ? "Switch to Teacher (faculty.ml)"
                  : "Switch to Admin (admin_root)"}
              </button>
              <button
                type="button"
                onClick={() => setShowSwitchModal(false)}
                className="py-2.5 px-4 rounded-xl border border-[#E4DDCA] bg-[#FBF8F0] hover:bg-[#EDE8D8] text-xs font-bold text-[#77735F] cursor-pointer text-center"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  return (
    <>
      {/* Desktop Persistent Sidebar */}
      <aside className="hidden lg:flex w-64 flex-col fixed inset-y-0 z-20 shadow-xl border-r border-[#EDE8D8]/10">
        {sidebarContent}
      </aside>

      {/* Mobile Drawer Overlay */}
      {isOpen && (
        <div className="fixed inset-0 z-40 lg:hidden flex">
          <div
            className="fixed inset-0 bg-black/50 backdrop-blur-xs transition-opacity"
            onClick={onClose}
          />
          <div className="relative flex-1 flex flex-col max-w-xs w-full bg-[#3F451F] z-50 shadow-2xl">
            {sidebarContent}
          </div>
        </div>
      )}

      {/* Desktop Layout Spacer */}
      <div className="hidden lg:block w-64 shrink-0" />
    </>
  );
}
