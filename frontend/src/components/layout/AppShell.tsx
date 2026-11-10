"use client";

import React, { useState } from "react";
import { useAuth } from "@/hooks/useAuth";
import { Sidebar, Header } from "@/components/layout";
import { LoginView } from "@/components/auth/LoginView";

interface AppShellProps {
  children: React.ReactNode;
  title?: string;
}

export function AppShell({ children, title = "Dashboard" }: AppShellProps) {
  const { isAuthenticated, isLoading } = useAuth();
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);

  // 1. Silent refresh / initial session verification
  if (isLoading) {
    return (
      <div className="min-h-screen bg-[#F2EDE0] flex items-center justify-center p-6 select-none">
        <div className="flex flex-col items-center space-y-4">
          <div className="w-12 h-12 rounded-2xl bg-[#EDE8D8] border border-[#E4DDCA] flex items-center justify-center animate-spin">
            <svg className="w-6 h-6 text-[#6C5119]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </div>
          <p className="text-sm font-semibold text-[#77735F]">
            Connecting to RollCall AI...
          </p>
        </div>
      </div>
    );
  }

  // 2. Authentication Gate: If unauthenticated, present the login experience
  if (!isAuthenticated) {
    return <LoginView />;
  }

  // 3. Authenticated Application Shell with strict Visual Reference match
  return (
    <div className="flex min-h-screen bg-[#F2EDE0]">
      {/* Deep Olive Sidebar */}
      <Sidebar
        isOpen={isMobileSidebarOpen}
        onClose={() => setIsMobileSidebarOpen(false)}
      />

      {/* Main Workspace */}
      <div className="flex-1 flex flex-col min-w-0">
        <Header
          title={title}
          onMenuToggle={() => setIsMobileSidebarOpen(true)}
        />

        <main className="flex-1 p-4 sm:p-6 lg:p-8 overflow-y-auto">
          {children}
        </main>
      </div>
    </div>
  );
}

