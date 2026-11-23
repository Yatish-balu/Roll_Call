import React, { useState, useEffect, useRef, useMemo } from "react";

export interface FormBTimerProps {
  deadline: Date | string | number;
  totalDurationSeconds?: number;
  onExpire?: () => void;
  className?: string;
}

export const FormBTimer: React.FC<FormBTimerProps> = ({
  deadline,
  totalDurationSeconds = 1800, // default 30 mins window
  onExpire,
  className = "",
}) => {
  const targetTime = useMemo(() => new Date(deadline).getTime(), [deadline]);
  const [secondsRemaining, setSecondsRemaining] = useState<number>(() => {
    return Math.max(0, Math.floor((new Date(deadline).getTime() - Date.now()) / 1000));
  });

  const expiredRef = useRef(false);

  useEffect(() => {
    expiredRef.current = false;

    const tick = () => {
      const now = Date.now();
      const diff = Math.max(0, Math.floor((targetTime - now) / 1000));
      setSecondsRemaining(diff);

      if (diff <= 0 && !expiredRef.current) {
        expiredRef.current = true;
        if (onExpire) {
          onExpire();
        }
      }
    };

    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, [targetTime, onExpire]);

  const isExpired = secondsRemaining <= 0;
  // Danger threshold: under 5 minutes (300 seconds)
  const isNearExpiry = secondsRemaining <= 300 && !isExpired;

  // Calculate remaining progress %
  const progressPercent = Math.min(
    100,
    Math.max(0, (secondsRemaining / totalDurationSeconds) * 100)
  );

  // Minutes and seconds formatting
  const minutes = Math.floor(secondsRemaining / 60);
  const seconds = secondsRemaining % 60;
  const timeFormatted = `${minutes}m ${seconds.toString().padStart(2, "0")}s`;

  return (
    <div
      className={`rounded-2xl p-4 border transition-all duration-300 ${
        isExpired
          ? "bg-rose-50 border-rose-300 dark:bg-rose-950/30 dark:border-rose-800 text-rose-900 dark:text-rose-200"
          : isNearExpiry
          ? "bg-red-50/90 border-red-300 dark:bg-red-950/40 dark:border-red-800 text-red-900 dark:text-red-200 shadow-sm animate-pulse"
          : "bg-[#FBF8F0] border-[#E4DDCA] dark:bg-[#181913] dark:border-[#2C3022] text-[#24251C] dark:text-[#EDE8D8]"
      } ${className}`}
    >
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2.5">
          <span
            className={`w-3 h-3 rounded-full shrink-0 ${
              isExpired
                ? "bg-rose-600"
                : isNearExpiry
                ? "bg-red-500 animate-ping"
                : "bg-amber-500"
            }`}
          />
          <div>
            <span className="text-[11px] font-black uppercase tracking-[0.14em] text-[#77735F] dark:text-[#A9AE8C] block">
              Form-B Submission Window
            </span>
            <p className="text-sm sm:text-base font-extrabold tracking-tight font-mono">
              {isExpired ? (
                <span className="text-rose-700 dark:text-rose-400">
                  FORM-B CLOSED (DEADLINE PASSED)
                </span>
              ) : (
                <span
                  className={
                    isNearExpiry
                      ? "text-red-600 dark:text-red-400 font-black text-lg"
                      : "text-[#3F451F] dark:text-[#D2A847]"
                  }
                >
                  FORM-B CLOSES IN: <strong className="underline underline-offset-2">{timeFormatted}</strong>
                </span>
              )}
            </p>
          </div>
        </div>

        {/* Progress pill indicator */}
        <div className="text-right">
          <span
            className={`text-xs font-mono font-bold px-2 py-0.5 rounded-md border ${
              isExpired
                ? "bg-rose-100 border-rose-300 text-rose-800"
                : isNearExpiry
                ? "bg-red-100 border-red-300 text-red-800"
                : "bg-[#EDE8D8] border-[#E4DDCA] text-[#6C5119] dark:bg-[#2C3117] dark:border-[#2C3022] dark:text-[#D2A847]"
            }`}
          >
            {isExpired ? "0% TIME REMAINING" : `${Math.round(progressPercent)}% TIME LEFT`}
          </span>
        </div>
      </div>

      {/* Progress Bar: turns red near expiry */}
      <div className="mt-3">
        <div className="h-2.5 w-full bg-[#EDE8D8] dark:bg-[#2C3117] rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-1000 ${
              isExpired
                ? "bg-rose-600"
                : isNearExpiry
                ? "bg-red-600"
                : "bg-[#3F451F] dark:bg-[#D2A847]"
            }`}
            style={{ width: `${isExpired ? 0 : progressPercent}%` }}
          />
        </div>
      </div>

      {isNearExpiry && (
        <p className="text-[11px] font-bold text-red-700 dark:text-red-400 mt-2 flex items-center gap-1.5">
          <svg className="w-4 h-4 shrink-0 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          Warning: Less than 5 minutes remaining to submit room absentee list!
        </p>
      )}
    </div>
  );
};
