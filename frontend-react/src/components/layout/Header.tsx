import React, { useState, useRef, useEffect } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import {
  fetchInitializationState,
  fetchSessionAllocations,
  type SessionAllocation,
} from "@/services/api/sessions";
import {
  fetchAttendanceUnlockRequests,
  reviewAttendanceUnlockRequest,
} from "@/services/api/attendance";
import { todayIso } from "@/lib/schedule";

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
  unlockRequestId?: string;
  sessionId?: string;
  actionRequired?: boolean;
}

export function Header({ title = "Dashboard", onMenuToggle }: HeaderProps) {
  const { session, logout, isAdmin } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [showNotifications, setShowNotifications] = useState(false);
  const [showProfile, setShowProfile] = useState(false);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [isLoadingNotifications, setIsLoadingNotifications] = useState(false);
  const [reviewingId, setReviewingId] = useState<string | null>(null);

  const notifRef = useRef<HTMLDivElement>(null);
  const profileRef = useRef<HTMLDivElement>(null);

  const getRouteIcon = (pathname: string) => {
    if (pathname === "/") {
      return (
        <svg className="w-5 h-5 text-[#3F451F]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
        </svg>
      );
    }
    if (pathname.startsWith("/attendance")) {
      return (
        <svg className="w-5 h-5 text-[#3F451F]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
        </svg>
      );
    }
    if (pathname.startsWith("/timetable")) {
      return (
        <svg className="w-5 h-5 text-[#3F451F]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
        </svg>
      );
    }
    if (pathname.startsWith("/sessions")) {
      return (
        <svg className="w-5 h-5 text-[#3F451F]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      );
    }
    if (pathname.startsWith("/students")) {
      return (
        <svg className="w-5 h-5 text-[#3F451F]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
        </svg>
      );
    }
    if (pathname.startsWith("/assistant")) {
      return (
        <svg className="w-5 h-5 text-[#3F451F]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
        </svg>
      );
    }
    if (pathname.startsWith("/reports")) {
      return (
        <svg className="w-5 h-5 text-[#3F451F]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
        </svg>
      );
    }
    if (pathname.startsWith("/defaulters")) {
      return (
        <svg className="w-5 h-5 text-[#3F451F]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
      );
    }
    if (pathname.startsWith("/calendar")) {
      return (
        <svg className="w-5 h-5 text-[#3F451F]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
        </svg>
      );
    }
    if (pathname.startsWith("/profile") || pathname.startsWith("/settings")) {
      return (
        <svg className="w-5 h-5 text-[#3F451F]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
        </svg>
      );
    }
    if (pathname.startsWith("/exams")) {
      return (
        <svg className="w-5 h-5 text-[#3F451F]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
      );
    }
    if (pathname.startsWith("/invigilation")) {
      return (
        <svg className="w-5 h-5 text-[#3F451F]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
        </svg>
      );
    }
    return (
      <svg className="w-5 h-5 text-[#3F451F]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h7" />
      </svg>
    );
  };

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

  /**
   * Notifications are derived from the real backend state:
   * - Today's class slots & initialisation status
   * - Teacher attendance unlock permission requests (for Admin to review)
   * - Status outcome alerts of unlock requests (for Faculty)
   */
  const loadNotifications = React.useCallback(async () => {
    setIsLoadingNotifications(true);
    const today = todayIso();
    const items: NotificationItem[] = [];

    // 1. Fetch attendance unlock permission requests
    try {
      if (isAdmin) {
        // Admin sees all PENDING unlock requests from teachers
        const unlockReqs = await fetchAttendanceUnlockRequests({ status: "PENDING" });
        unlockReqs.forEach((req) => {
          items.push({
            id: `unlock-${req.request_id}`,
            title: `🔒 Permission Request: ${req.teacher_name || req.teacher_id}`,
            description: `${req.subject_code ? `${req.subject_code} (${req.session_date || "Session"})` : `Session ${req.session_id.slice(0, 16)}`} • "${req.reason}"${req.target_usns ? ` • Target: ${req.target_usns}` : ""}`,
            time: req.created_at ? req.created_at.slice(0, 10) : "Pending",
            read: false,
            type: "warning",
            unlockRequestId: req.request_id,
            sessionId: req.session_id,
            actionRequired: true,
          });
        });
      } else {
        // Teachers see the status of their submitted requests
        const myRequests = await fetchAttendanceUnlockRequests();
        myRequests.slice(0, 5).forEach((req) => {
          if (req.status === "APPROVED") {
            items.push({
              id: `unlock-${req.request_id}`,
              title: `✅ Permission Granted: ${req.subject_code || "Session"}`,
              description: `Admin approved your edit request. Session unlocked until ${
                req.expires_at
                  ? new Date(req.expires_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                  : "tomorrow"
              }.`,
              time: req.reviewed_at ? req.reviewed_at.slice(0, 10) : "Today",
              read: false,
              type: "success",
              sessionId: req.session_id,
            });
          } else if (req.status === "REJECTED") {
            items.push({
              id: `unlock-${req.request_id}`,
              title: `❌ Permission Denied: ${req.subject_code || "Session"}`,
              description: `Admin declined your edit request${req.admin_notes ? `: "${req.admin_notes}"` : "."}`,
              time: req.reviewed_at ? req.reviewed_at.slice(0, 10) : "Today",
              read: false,
              type: "warning",
              sessionId: req.session_id,
            });
          } else if (req.status === "PENDING") {
            items.push({
              id: `unlock-${req.request_id}`,
              title: `⏳ Permission Pending: ${req.subject_code || "Session"}`,
              description: `Awaiting admin approval: "${req.reason}".`,
              time: req.created_at ? req.created_at.slice(0, 10) : "Pending",
              read: true,
              type: "info",
              sessionId: req.session_id,
            });
          }
        });
      }
    } catch {
      // Ignore if unlock requests endpoint fails temporarily
    }

    try {
      const allocations = await fetchSessionAllocations({ date: today });
      const slots: SessionAllocation[] = allocations.items || [];
      if (slots.length > 0) {
        slots.forEach((slot) => {
          items.push({
            id: `slot-${slot.allocation_id}`,
            title: `${slot.subject || slot.subject_code || "Class"} · ${slot.start_time}`,
            description: `${slot.room_id || "Room not allocated"}${
              slot.batch_id ? ` · Batch ${slot.batch_id}` : ""
            }`,
            time: "Today",
            read: false,
            type: "info",
          });
        });
      }
    } catch {
      // The class list is unavailable - no notification is shown for it.
    }

    try {
      const state = await fetchInitializationState(today);
      items.push({
        id: `init-${state.date}`,
        title:
          state.status === "INITIALIZED"
            ? "Today's sessions are ready"
            : state.status === "PENDING"
            ? "Session initialisation pending"
            : state.status === "FAILED"
            ? "Session initialisation failed"
            : "No classes scheduled today",
        description: state.message,
        time: "Today",
        read: state.status === "NO_CLASSES",
        type:
          state.status === "FAILED"
            ? "warning"
            : state.status === "INITIALIZED"
            ? "success"
            : "info",
      });
    } catch {
      // Initialisation state unavailable - no notification is shown for it.
    }

    setNotifications(items);
    setIsLoadingNotifications(false);
  }, [isAdmin]);

  useEffect(() => {
    void loadNotifications();
    const handleSync = () => {
      void loadNotifications();
    };
    window.addEventListener("rollcall-unlock-request-updated", handleSync);
    window.addEventListener("rollcall-attendance-updated", handleSync);
    return () => {
      window.removeEventListener("rollcall-unlock-request-updated", handleSync);
      window.removeEventListener("rollcall-attendance-updated", handleSync);
    };
  }, [loadNotifications]);

  const handleReviewFromNotification = async (
    requestId: string,
    decision: "APPROVED" | "REJECTED",
    e: React.MouseEvent
  ) => {
    e.stopPropagation();
    setReviewingId(requestId);
    try {
      await reviewAttendanceUnlockRequest(requestId, {
        decision,
        unlock_hours: 24,
        admin_notes: decision === "APPROVED" ? "Approved via Quick Notification" : "Rejected via Quick Notification",
      });
      window.dispatchEvent(new CustomEvent("rollcall-unlock-request-updated"));
      window.dispatchEvent(new CustomEvent("rollcall-attendance-updated"));
      await loadNotifications();
    } catch (err) {
      console.error("Failed to review unlock request from notification:", err);
    } finally {
      setReviewingId(null);
    }
  };

  const handleSignOut = async () => {
    setShowProfile(false);
    await logout();
    navigate("/login");
  };

  return (
    <header className="h-16 px-4 sm:px-6 lg:px-8 flex items-center justify-between bg-transparent shrink-0 relative z-30 border-b border-[#333D19]/[0.08]">
      {/* Left: Mobile Toggle & Page Title with Contextual Route Icon */}
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
          <div className="w-8 h-8 rounded-xl bg-[#EDE8D8] border border-[#E4DDCA] flex items-center justify-center shrink-0 shadow-2xs">
            {getRouteIcon(location.pathname)}
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
                {isLoadingNotifications ? (
                  <div className="p-6 text-center text-xs text-[#77735F]">
                    Loading today's schedule...
                  </div>
                ) : notifications.length === 0 ? (
                  <div className="p-6 text-center text-xs text-[#77735F]">
                    Nothing scheduled for today.
                  </div>
                ) : (
                  notifications.map((item) => (
                    <div
                      key={item.id}
                      onClick={() => {
                        if (item.sessionId) {
                          setShowNotifications(false);
                          navigate(`/attendance?sessionId=${encodeURIComponent(item.sessionId)}`);
                        }
                      }}
                      className={`p-3.5 transition-colors ${
                        item.read ? "bg-[#FBF8F0]" : "bg-[#EDE8D8]/30 font-medium"
                      } hover:bg-[#EDE8D8]/60 ${item.sessionId ? "cursor-pointer" : ""}`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="space-y-1 flex-1">
                          <div className="flex items-center space-x-1.5">
                            {!item.read && (
                              <span className="w-1.5 h-1.5 rounded-full bg-[#E06D20] shrink-0" />
                            )}
                            <p className="text-xs font-bold text-[#24251C]">{item.title}</p>
                          </div>
                          <p className="text-[11px] text-[#77735F] leading-relaxed">
                            {item.description}
                          </p>

                          {/* Quick Actions for Admin on Pending Permission Requests */}
                          {item.actionRequired && item.unlockRequestId && (
                            <div className="mt-2.5 pt-2 border-t border-[#E4DDCA]/60 flex items-center gap-2 flex-wrap">
                              <button
                                type="button"
                                disabled={reviewingId === item.unlockRequestId}
                                onClick={(e) => handleReviewFromNotification(item.unlockRequestId!, "APPROVED", e)}
                                className="px-2.5 py-1 rounded-lg bg-emerald-700 hover:bg-emerald-800 text-white font-bold text-[10px] shadow-2xs transition-all cursor-pointer disabled:opacity-50"
                              >
                                {reviewingId === item.unlockRequestId ? "Approving..." : "✅ Approve (24h)"}
                              </button>
                              <button
                                type="button"
                                disabled={reviewingId === item.unlockRequestId}
                                onClick={(e) => handleReviewFromNotification(item.unlockRequestId!, "REJECTED", e)}
                                className="px-2.5 py-1 rounded-lg bg-stone-200 hover:bg-rose-100 text-stone-700 hover:text-rose-800 font-bold text-[10px] transition-all cursor-pointer disabled:opacity-50"
                              >
                                ❌ Reject
                              </button>
                              {item.sessionId && (
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setShowNotifications(false);
                                    navigate(`/attendance?sessionId=${encodeURIComponent(item.sessionId!)}`);
                                  }}
                                  className="ml-auto text-[10px] font-bold text-[#6C5119] hover:underline cursor-pointer"
                                >
                                  View Session →
                                </button>
                              )}
                            </div>
                          )}
                        </div>
                        <span className="text-[10px] text-[#77735F]/80 whitespace-nowrap shrink-0">
                          {item.time}
                        </span>
                      </div>
                    </div>
                  ))
                )}
              </div>

              {isAdmin && (
                <div className="p-2.5 bg-[#EDE8D8]/50 border-t border-[#E4DDCA] text-center">
                  <button
                    onClick={() => {
                      setShowNotifications(false);
                      navigate("/faculty");
                    }}
                    className="text-xs font-bold text-[#6C5119] hover:underline cursor-pointer inline-flex items-center gap-1"
                  >
                    <span>Open Admin Command Center</span>
                    <span>→</span>
                  </button>
                </div>
              )}
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
                  <span>Settings</span>
                </Link>

                <Link
                  to="/profile"
                  onClick={() => setShowProfile(false)}
                  className="w-full flex items-center space-x-2.5 px-3 py-2 rounded-xl text-xs font-semibold text-[#24251C] hover:bg-[#EDE8D8]/60 transition-colors"
                >
                  <svg className="w-4 h-4 text-[#77735F]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                  </svg>
                  <span>My Profile</span>
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

              {isAdmin && (
                <div className="p-2.5 bg-[#EDE8D8]/50 border-t border-[#E4DDCA] text-center">
                  <button
                    onClick={() => {
                      setShowNotifications(false);
                      navigate("/faculty");
                    }}
                    className="text-xs font-bold text-[#6C5119] hover:underline cursor-pointer inline-flex items-center gap-1"
                  >
                    <span>Open Admin Command Center</span>
                    <span>→</span>
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
