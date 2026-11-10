"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useBackendHealth } from "@/hooks/useBackendHealth";
import { useAuth } from "@/hooks/useAuth";

interface NavItem {
  name: string;
  href: string;
  icon: React.ReactNode;
}

interface SidebarProps {
  isOpen?: boolean;
  onClose?: () => void;
}

export function Sidebar({ isOpen = false, onClose }: SidebarProps) {
  const pathname = usePathname();
  const { isOnline } = useBackendHealth();
  const { logout } = useAuth();

  const mainNav: NavItem[] = [
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
      name: "Students",
      href: "/students",
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
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
      name: "Faculty & Depts",
      href: "/faculty",
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
        </svg>
      ),
    },
    {
      name: "Rooms",
      href: "/rooms",
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h18M3 14h18m-9-4v8m-7 4h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
        </svg>
      ),
    },
  ];

  const secondaryNav: NavItem[] = [
    {
      name: "Reports",
      href: "/reports",
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
        </svg>
      ),
    },
    {
      name: "AI Assistant",
      href: "/assistant",
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
        </svg>
      ),
    },
  ];

  const isLinkActive = (href: string) => {
    if (href === "/") {
      return pathname === "/";
    }
    return pathname.startsWith(href);
  };

  const sidebarContent = (
    <div className="flex flex-col h-full bg-[#3F451F] text-[#EDE8D8] select-none relative overflow-hidden">
      {/* Brand Header */}
      <div className="p-6 pb-5 flex items-center space-x-3 border-b border-[#EDE8D8]/10">
        <div className="w-9 h-9 rounded-lg bg-[#EDE8D8]/15 flex items-center justify-center text-[#EDE8D8]">
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

      {/* Navigation Sections */}
      <div className="flex-1 py-4 px-3 space-y-4 overflow-y-auto z-10 scrollbar-thin">
        {/* Core Nav Group */}
        <nav className="space-y-1">
          {mainNav.map((item) => {
            const isActive = isLinkActive(item.href);
            return (
              <Link
                key={item.name}
                href={item.href}
                onClick={onClose}
                className={`flex items-center space-x-3 px-3.5 py-2.5 rounded-xl text-xs sm:text-sm font-semibold transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#EDE8D8] ${
                  isActive
                    ? "bg-[#A77A13] text-white shadow-sm font-bold"
                    : "text-[#EDE8D8]/80 hover:text-[#EDE8D8] hover:bg-[#EDE8D8]/10"
                }`}
              >
                <span className={isActive ? "text-white" : "text-[#EDE8D8]/70"}>
                  {item.icon}
                </span>
                <span>{item.name}</span>
              </Link>
            );
          })}
        </nav>

        {/* Separator */}
        <div className="border-t border-[#EDE8D8]/10 mx-2" />

        {/* Secondary Nav Group */}
        <nav className="space-y-1">
          {secondaryNav.map((item) => {
            const isActive = isLinkActive(item.href);
            return (
              <Link
                key={item.name}
                href={item.href}
                onClick={onClose}
                className={`flex items-center space-x-3 px-3.5 py-2.5 rounded-xl text-xs sm:text-sm font-semibold transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#EDE8D8] ${
                  isActive
                    ? "bg-[#A77A13] text-white shadow-sm font-bold"
                    : "text-[#EDE8D8]/80 hover:text-[#EDE8D8] hover:bg-[#EDE8D8]/10"
                }`}
              >
                <span className={isActive ? "text-white" : "text-[#EDE8D8]/70"}>
                  {item.icon}
                </span>
                <span>{item.name}</span>
              </Link>
            );
          })}
        </nav>
      </div>

      {/* Decorative Organic Wave Graphic */}
      <div className="absolute -bottom-6 left-0 right-0 pointer-events-none opacity-40">
        <svg
          viewBox="0 0 256 120"
          className="w-full text-[#A77A13]/30 fill-current"
          preserveAspectRatio="none"
        >
          <path d="M0,40 C60,90 120,10 180,60 C220,90 240,30 256,50 L256,120 L0,120 Z" />
          <path
            d="M0,60 C80,20 140,80 200,40 C230,20 245,50 256,40 L256,120 L0,120 Z"
            className="text-[#6C5119]/40 fill-current"
          />
        </svg>
      </div>

      {/* Footer System Status & Settings */}
      <div className="p-4 border-t border-[#EDE8D8]/10 z-10 space-y-2 bg-[#3F451F]/90 backdrop-blur-xs">
        {/* Backend Connectivity Status Pill */}
        <div className="flex items-center space-x-2 px-3 py-1.5 rounded-full bg-[#EDE8D8]/10 text-xs w-fit">
          <span
            className={`w-2 h-2 rounded-full ${
              isOnline ? "bg-emerald-400 animate-pulse" : "bg-amber-400"
            }`}
          />
          <span className="text-[11px] font-medium text-[#EDE8D8]/90">
            {isOnline ? "Backend Online" : "Connecting..."}
          </span>
        </div>

        {/* Settings & Sign Out */}
        <div className="pt-1 space-y-0.5">
          <Link
            href="/settings"
            onClick={onClose}
            className={`flex items-center space-x-3 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
              pathname === "/settings"
                ? "bg-[#A77A13] text-white font-bold"
                : "text-[#EDE8D8]/80 hover:text-[#EDE8D8] hover:bg-[#EDE8D8]/10"
            }`}
          >
            <svg className="w-4 h-4 text-[#EDE8D8]/70" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            <span>Settings</span>
          </Link>

          <button
            onClick={() => {
              void logout();
              if (onClose) onClose();
            }}
            className="w-full flex items-center space-x-3 px-3 py-2 rounded-lg text-xs font-medium text-[#EDE8D8]/80 hover:text-rose-300 hover:bg-rose-500/10 transition-colors text-left cursor-pointer"
          >
            <svg className="w-4 h-4 text-[#EDE8D8]/70" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
            </svg>
            <span>Sign Out</span>
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop Fixed Sidebar */}
      <aside className="hidden lg:block w-64 h-screen sticky top-0 shrink-0 shadow-lg">
        {sidebarContent}
      </aside>

      {/* Mobile Drawer Overlay */}
      {isOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className="fixed inset-0 bg-black/50 backdrop-blur-xs transition-opacity"
            onClick={onClose}
          />
          <div className="fixed inset-y-0 left-0 w-64 shadow-2xl">
            {sidebarContent}
          </div>
        </div>
      )}
    </>
  );
}
