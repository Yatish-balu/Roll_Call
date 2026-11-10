import { useAuth } from "@/hooks/useAuth";

interface HeaderProps {
  title?: string;
  onMenuToggle?: () => void;
}

export function Header({ title = "Dashboard", onMenuToggle }: HeaderProps) {
  const { session } = useAuth();

  const todayFormatted = new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date());

  const displayName = session?.name || session?.userId || "Teacher";
  const userInitial = displayName.charAt(0).toUpperCase();

  return (
    <header className="h-16 px-4 sm:px-6 lg:px-8 flex items-center justify-between bg-transparent shrink-0">
      {/* Left: Mobile Toggle & Page Title with Grid Icon */}
      <div className="flex items-center space-x-3">
        {onMenuToggle && (
          <button
            onClick={onMenuToggle}
            className="lg:hidden p-2 rounded-lg text-[#24251C] hover:bg-[#E4DDCA]/50 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
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
        <div className="hidden sm:flex items-center space-x-2 px-3.5 py-1.5 rounded-xl bg-[#FBF8F0] border border-[#E4DDCA] shadow-2xs text-xs font-semibold text-[#24251C]">
          <svg className="w-4 h-4 text-[#77735F]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
          <span>{todayFormatted}</span>
        </div>

        <button
          className="relative p-2 rounded-xl bg-[#FBF8F0] border border-[#E4DDCA] text-[#24251C] hover:bg-[#EDE8D8]/50 transition-colors shadow-2xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
          aria-label="Notifications"
        >
          <svg className="w-5 h-5 text-[#24251C]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
          </svg>
          <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-[#E06D20] ring-2 ring-[#FBF8F0]" />
        </button>

        <div
          title={`${displayName} (${session?.role || "User"})`}
          className="w-9 h-9 rounded-full bg-[#3F451F] text-[#EDE8D8] flex items-center justify-center font-bold text-sm shadow-xs border border-[#E4DDCA] select-none"
        >
          {userInitial}
        </div>
      </div>
    </header>
  );
}

