import React from "react";

interface FormBTimerProps {
  cutoffAt?: string;
  status: "SCHEDULED" | "OPEN" | "SUBMITTED" | "LATE_LOCKED";
  onExpire?: () => void;
}

/**
 * Demo mode: the Form-B cutoff/lock has been removed.
 *
 * The backend no longer expires a Form-B submission window (cutoff_minutes = 0),
 * so there is no countdown or "Late-Locked" banner to display.  The component
 * is kept as a no-op so existing imports continue to work.
 */
export function FormBTimer(_props: FormBTimerProps) {
  return null;
}

export default FormBTimer;
