import React from "react";
import { Link, Navigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";

interface ProtectedRouteProps {
  children: React.ReactNode;
  allowedRoles?: ("ADMIN" | "FACULTY" | "VIEWER")[];
  pageTitle?: string;
}

export function ProtectedRoute({
  children,
  allowedRoles,
  pageTitle = "this section",
}: ProtectedRouteProps) {
  const { isAuthenticated, isLoading, session } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-[50vh] flex items-center justify-center">
        <div className="w-8 h-8 rounded-xl border-2 border-[#6C5119] border-t-transparent animate-spin" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  const userRole = session.role;
  // Role hierarchy: ADMIN > FACULTY > VIEWER
  const isAuthorized =
    !allowedRoles ||
    allowedRoles.length === 0 ||
    (userRole && (
      allowedRoles.includes(userRole) ||
      userRole === "ADMIN" ||
      (userRole === "FACULTY" && allowedRoles.includes("VIEWER"))
    ));

  if (!isAuthorized) {
    return (
      <div className="max-w-xl mx-auto my-12 p-8 bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl shadow-sm text-center space-y-4 animate-in fade-in zoom-in-95 duration-150">
        <div className="w-14 h-14 rounded-2xl bg-amber-100 text-amber-800 border border-amber-200 flex items-center justify-center mx-auto shadow-2xs">
          <svg className="w-7 h-7" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
            />
          </svg>
        </div>

        <div className="space-y-1.5">
          <span className="px-2.5 py-0.5 rounded-full text-[10px] font-black uppercase tracking-wider bg-rose-100 text-rose-800 border border-rose-200">
            HTTP 403 • FORBIDDEN
          </span>
          <h2 className="text-xl font-extrabold text-[#24251C] tracking-tight">
            Access Denied
          </h2>
          <p className="text-xs text-[#77735F] leading-relaxed max-w-md mx-auto">
            Your current authenticated role (
            <span className="font-mono font-bold text-[#24251C]">
              {userRole || "UNKNOWN"}
            </span>
            ) does not have authorization to view {pageTitle}. This resource is restricted to{" "}
            <span className="font-semibold text-[#24251C]">
              {allowedRoles?.join(", ")}
            </span>{" "}
            personnel.
          </p>
        </div>

        <div className="pt-3 flex items-center justify-center gap-3">
          <Link
            to="/"
            className="px-4 py-2.5 rounded-xl bg-[#3F451F] text-[#EDE8D8] text-xs font-bold hover:bg-[#343919] transition-all shadow-2xs cursor-pointer"
          >
            Return to Authorized Workspace
          </Link>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}

