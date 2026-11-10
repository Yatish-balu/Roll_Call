import React, { useState, useRef, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";

interface HeaderProps {
  title?: string;
  onMenuToggle?: () => void;
}

interface NotificationItem {
  id: string;
  title: string;
  description: string;
  time: string;
  read: boolean;
  type: "success" | "warning" | "info";
}

const INITIAL_NOTIFICATIONS: NotificationItem[] = [
  {
    id: "notif-1",
    title: "Attendance Synchronized",
    description: "Distributed Systems (SESS-20261024-01) roster synced to server.",
    time: "10 mins ago",
    read: false,
    type: "success",
  },
  {
    id: "notif-2",
    title: "Upcoming 2-Hour Laboratory",
    description: "Database Systems Lab scheduled at 14:00 PM in LAB-1.",
    time: "Today",
    read: false,
    type: "info",
  },
  {
    id: "notif-3",
    title: "Institutional Attendance Policy",
    description: "Defaulter threshold active at 75%. Automated reports ready.",
    time: "1 hour ago",
    read: true,
    type: "warning",
  },
];

export function Header({ title = "Dashboard", onMenuToggle }: HeaderProps) {
  const { session, logout, isAdmin } = useAuth();
  const navigate = useNavigate();
  const [showNotifications, setShowNotifications] = useState(false);
  const [showProfile, setShowProfile] = useState(false);
  const [notifications, setNotifications] = useState<NotificationItem[]>(INITIAL_NOTIFICATIONS);

  const notifRef = useRef<HTMLDivElement>(null);
  const profileRef = useRef<HTMLDivElement>(null);

  const unreadCount = notifications.filter((n) => !n.read).length;

  const todayFormatted = new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date());

  const displayName = session?.name || session?.userId || "User";
  const userInitial = displayName.charAt(0).toUpperCase();

  // Close menus when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (notifRef.current && !notifRef.current.contains(event.target as Node)) {
        setShowNotifications(false);
      }
      if (profileRef.current && !profileRef.current.contains(event.target as Node)) {
        setShowProfile(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleMarkAllRead = () => {
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
  };

  const handleClearNotifications = () => {
    setNotifications([]);
  };

  const handleSignOut = async () => {
    setShowProfile(false);
    await logout();
    navigate("/login");
  };

  return (
    <header className="h-16 px-4 sm:px-6 lg:px-8 flex items-center justify-between bg-transparent shrink-0 relative z-30">
      {/* Left: Mobile Toggle & Page Title with Grid Icon */}
      <div className="flex items-center space-x-3">
        {onMenuToggle && (
          <button
            onClick={onMenuToggle}
            className="lg:hidden p-2 rounded-xl text-[#24251C] hover:bg-[#E4DDCA]/50 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119] cursor-pointer"
            aria-label="Open sidebar"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
        )}

        <div className="flex items-center space-x-2.5">
          <div className="grid grid-cols-3 gap-0.5 w-5 h-5 text-[#24251C]">
            <span className="w-1.5 h-1.5 bg-[#24251C] rounded-[1px]" />
            <span className="w-1.5 h-1.5 bg-[#24251C] rounded-[1px]" />
            <span className="w-1.5 h-1.5 bg-[#24251C] rounded-[1px]" />
            <span className="w-1.5 h-1.5 bg-[#24251C] rounded-[1px]" />
            <span className="w-1.5 h-1.5 bg-[#24251C] rounded-[1px]" />
            <span className="w-1.5 h-1.5 bg-[#24251C] rounded-[1px]" />
            <span className="w-1.5 h-1.5 bg-[#24251C] rounded-[1px]" />
            <span className="w-1.5 h-1.5 bg-[#24251C] rounded-[1px]" />
            <span className="w-1.5 h-1.5 bg-[#24251C] rounded-[1px]" />
          </div>

          <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-[#24251C]">
            {title}
          </h1>
        </div>
      </div>

      {/* Right: Date Pill, Notification Bell, User Avatar */}
      <div className="flex items-center space-x-3 sm:space-x-4">
        {/* Date Pill */}
        <div className="hidden sm:flex items-center space-x-2 px-3.5 py-1.5 rounded-xl bg-[#FBF8F0] border border-[#E4DDCA] shadow-2xs text-xs font-semibold text-[#24251C]">
          <svg className="w-4 h-4 text-[#77735F]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
          <span>{todayFormatted}</span>
        </div>

        {/* Notification Bell & Dropdown */}
        <div className="relative" ref={notifRef}>
          <button
            onClick={() => {
              setShowNotifications((prev) => !prev);
              setShowProfile(false);
            }}
            className="relative p-2 rounded-xl bg-[#FBF8F0] border border-[#E4DDCA] text-[#24251C] hover:bg-[#EDE8D8]/60 transition-colors shadow-2xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119] cursor-pointer"
            aria-label="Notifications"
          >
            <svg className="w-5 h-5 text-[#24251C]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
            </svg>
            {unreadCount > 0 && (
              <span className="absolute -top-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full bg-[#E06D20] text-[9px] font-black text-white shadow-xs">
                {unreadCount}
              </span>
            )}
          </button>

          {/* Notifications Dropdown Panel */}
          {showNotifications && (
            <div className="absolute right-0 mt-2 w-80 sm:w-96 rounded-2xl bg-[#FBF8F0] border border-[#E4DDCA] shadow-xl overflow-hidden animate-in fade-in zoom-in-95 duration-150 z-50">
              <div className="p-3.5 border-b border-[#E4DDCA] bg-[#EDE8D8]/50 flex items-center justify-between">
                <div className="flex items-center space-x-2">
                  <span className="text-xs font-bold text-[#24251C]">Notifications</span>
                  {unreadCount > 0 && (
                    <span className="px-2 py-0.5 rounded-full text-[10px] font-extrabold bg-[#3F451F] text-[#EDE8D8]">
                      {unreadCount} new
                    </span>
                  )}
                </div>
                <div className="flex items-center space-x-2">
                  {unreadCount > 0 && (
                    <button
                      onClick={handleMarkAllRead}
                      className="text-[11px] font-semibold text-[#6C5119] hover:underline cursor-pointer"
                    >
                      Mark all read
                    </button>
                  )}
                  {notifications.length > 0 && (
                    <button
                      onClick={handleClearNotifications}
                      className="text-[11px] font-medium text-[#77735F] hover:text-red-700 cursor-pointer"
                    >
                      Clear
                    </button>
                  )}
                </div>
              </div>

              <div className="max-h-80 overflow-y-auto divide-y divide-[#E4DDCA]/60">
                {notifications.length === 0 ? (
                  <div className="p-6 text-center text-xs text-[#77735F]">
                    No new notifications. You are all caught up!
                  </div>
                ) : (
                  notifications.map((item) => (
                    <div
                      key={item.id}
                      className={`p-3.5 transition-colors ${
                        item.read ? "bg-[#FBF8F0]" : "bg-[#EDE8D8]/30 font-medium"
                      } hover:bg-[#EDE8D8]/60`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="space-y-1">
                          <div className="flex items-center space-x-1.5">
                            {!item.read && (
                              <span className="w-1.5 h-1.5 rounded-full bg-[#E06D20]" />
                            )}
                            <p className="text-xs font-bold text-[#24251C]">{item.title}</p>
                          </div>
                          <p className="text-[11px] text-[#77735F] leading-relaxed">
                            {item.description}
                          </p>
                        </div>
                        <span className="text-[10px] text-[#77735F]/80 whitespace-nowrap">
                          {item.time}
                        </span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>

        {/* Profile Avatar & Interactive Dropdown */}
        <div className="relative" ref={profileRef}>
          <button
            onClick={() => {
              setShowProfile((prev) => !prev);
              setShowNotifications(false);
            }}
            className="w-9 h-9 rounded-full bg-[#3F451F] text-[#EDE8D8] flex items-center justify-center font-bold text-sm shadow-xs border border-[#E4DDCA] select-none hover:ring-2 hover:ring-[#6C5119] transition-all cursor-pointer"
            aria-label="User Profile"
          >
            {userInitial}
          </button>

          {/* Profile Dropdown Menu */}
          {showProfile && (
            <div className="absolute right-0 mt-2 w-72 rounded-2xl bg-[#FBF8F0] border border-[#E4DDCA] shadow-xl overflow-hidden animate-in fade-in zoom-in-95 duration-150 z-50">
              {/* Header section with role badge */}
              <div className="p-4 border-b border-[#E4DDCA] bg-[#EDE8D8]/40 space-y-2">
                <div className="flex items-center space-x-3">
                  <div className="w-10 h-10 rounded-full bg-[#3F451F] text-[#EDE8D8] flex items-center justify-center font-bold text-base shadow-xs border border-[#E4DDCA]">
                    {userInitial}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-bold text-[#24251C] truncate">
                      {displayName}
                    </p>
                    <p className="text-[11px] text-[#77735F] truncate">
                      {session?.userId ? `${session.userId}@rollcall.internal` : "Authenticated User"}
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-1.5 flex-wrap pt-1">
                  <span className={`px-2 py-0.5 rounded-md text-[10px] font-black uppercase tracking-wider ${
                    isAdmin
                      ? "bg-[#6C5119] text-[#EDE8D8]"
                      : "bg-[#3F451F] text-[#EDE8D8]"
                  }`}>
                    {isAdmin ? "System Admin" : "Teacher / Faculty"}
                  </span>
                  {session?.subjectCodes && session.subjectCodes.length > 0 && (
                    session.subjectCodes.map((code) => (
                      <span
                        key={code}
                        className="px-1.5 py-0.5 rounded-md text-[10px] font-bold bg-[#EDE8D8] text-[#6C5119] border border-[#E4DDCA]"
                      >
                        {code}
                      </span>
                    ))
                  )}
                </div>
              </div>

              {/* Action Links */}
              <div className="p-2 space-y-1">
                <Link
                  to="/settings"
                  onClick={() => setShowProfile(false)}
                  className="w-full flex items-center space-x-2.5 px-3 py-2 rounded-xl text-xs font-semibold text-[#24251C] hover:bg-[#EDE8D8]/60 transition-colors"
                >
                  <svg className="w-4 h-4 text-[#77735F]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  </svg>
                  <span>My Profile & Settings</span>
                </Link>

                <Link
                  to="/timetable"
                  onClick={() => setShowProfile(false)}
                  className="w-full flex items-center space-x-2.5 px-3 py-2 rounded-xl text-xs font-semibold text-[#24251C] hover:bg-[#EDE8D8]/60 transition-colors"
                >
                  <svg className="w-4 h-4 text-[#77735F]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                  </svg>
                  <span>Timetable</span>
                </Link>

                <div className="border-t border-[#E4DDCA] my-1" />

                <button
                  type="button"
                  onClick={handleSignOut}
                  className="w-full flex items-center space-x-2.5 px-3 py-2 rounded-xl text-xs font-bold text-rose-700 hover:bg-rose-50 transition-colors cursor-pointer text-left"
                >
                  <svg className="w-4 h-4 text-rose-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                  </svg>
                  <span>Sign Out</span>
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
