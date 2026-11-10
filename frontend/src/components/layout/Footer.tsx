import React from "react";
import { API_BASE_URL } from "@/config/api";

export function Footer() {
  return (
    <footer className="w-full border-t border-slate-200 bg-white py-6 dark:border-slate-800 dark:bg-slate-900">
      <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-4 px-4 text-xs text-slate-500 sm:flex-row sm:px-6 lg:px-8">
        <div>
          <p className="font-medium text-slate-700 dark:text-slate-300">
            RollCall AI • Phase 7.1 Architecture
          </p>
          <p className="text-slate-400">
            Frontend: Next.js + TypeScript + Tailwind CSS | Backend: FastAPI + SQLAlchemy
          </p>
        </div>

        <div className="flex items-center gap-4">
          <a
            href={`${API_BASE_URL}/docs`}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-indigo-600 transition-colors underline underline-offset-4"
          >
            Backend API Docs (/docs)
          </a>
          <span className="text-slate-300 dark:text-slate-700">•</span>
          <a
            href={`${API_BASE_URL}/health`}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-indigo-600 transition-colors underline underline-offset-4"
          >
            Health Check (/health)
          </a>
        </div>
      </div>
    </footer>
  );
}

