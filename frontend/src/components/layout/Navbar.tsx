import React from "react";
import { Badge } from "@/components/ui/Badge";
import { APP_ENV } from "@/config/api";

export interface NavbarProps {
  isBackendOnline?: boolean;
}

export function Navbar({ isBackendOnline }: NavbarProps) {
  return (
    <header className="sticky top-0 z-40 w-full border-b border-slate-200/80 bg-white/80 backdrop-blur-md dark:border-slate-800/80 dark:bg-slate-900/80">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-600 text-white font-bold text-lg shadow-sm">
            R
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-slate-900 tracking-tight dark:text-slate-100">
                RollCall AI
              </span>
              <span className="text-xs text-slate-400 font-medium">v0.2.0</span>
            </div>
            <p className="text-xs text-slate-500 hidden sm:block">
              Automated Attendance & Reconciliation System
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Badge variant="neutral" size="sm" className="hidden md:inline-flex uppercase tracking-wider text-[10px]">
            {APP_ENV}
          </Badge>

          {isBackendOnline !== undefined && (
            <Badge
              variant={isBackendOnline ? "success" : "error"}
              size="sm"
              className="flex items-center"
            >
              <span
                className={`inline-block h-1.5 w-1.5 rounded-full ${
                  isBackendOnline ? "bg-emerald-500 animate-pulse" : "bg-rose-500"
                }`}
              />
              {isBackendOnline ? "API Connected" : "API Offline"}
            </Badge>
          )}
        </div>
      </div>
    </header>
  );
}

