import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import {
  DESIGNATIONS,
  EXPERTISE_SUGGESTIONS,
  loadFacultyProfile,
  saveFacultyProfile,
  type FacultyProfile,
  type ProfileStorage,
} from "@/services/api/profile";

type TagInput = "expertise" | "masteredSubjects";

export function MyProfileView() {
  const { session, isAdmin } = useAuth();
  const userId = session?.userId || "anonymous";

  const [profile, setProfile] = useState<FacultyProfile | null>(null);
  const [storage, setStorage] = useState<ProfileStorage>("device");
  const [notice, setNotice] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [tagDraft, setTagDraft] = useState<Record<TagInput, string>>({
    expertise: "",
    masteredSubjects: "",
  });
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const loadProfile = useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      const result = await loadFacultyProfile(userId);
      setProfile(result.profile);
      setStorage(result.storage);
      setNotice(result.notice);
    } catch (err: unknown) {
      setLoadError(
        err instanceof Error ? err.message : "The faculty profile could not be loaded."
      );
    } finally {
      setIsLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    void loadProfile();
  }, [loadProfile]);

  const assignedSubjects = useMemo(() => session?.subjectCodes ?? [], [session?.subjectCodes]);

  const update = <K extends keyof FacultyProfile>(key: K, value: FacultyProfile[K]) => {
    setProfile((prev) => (prev ? { ...prev, [key]: value } : prev));
    setSaveMessage(null);
    setSaveError(null);
  };

  const addTag = (kind: TagInput) => {
    const draft = tagDraft[kind].trim();
    if (!draft || !profile) return;
    const existing = profile[kind];
    if (existing.some((item) => item.toLowerCase() === draft.toLowerCase())) {
      setTagDraft((prev) => ({ ...prev, [kind]: "" }));
      return;
    }
    update(kind, [...existing, draft]);
    setTagDraft((prev) => ({ ...prev, [kind]: "" }));
  };

  const removeTag = (kind: TagInput, tag: string) => {
    if (!profile) return;
    update(
      kind,
      profile[kind].filter((item) => item !== tag)
    );
  };

  const handlePhotoChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file || !profile) return;
    if (!file.type.startsWith("image/")) {
      setSaveError("The profile photo must be an image file.");
      return;
    }
    if (file.size > 2 * 1024 * 1024) {
      setSaveError("The profile photo must be smaller than 2 MB.");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      update("photoUrl", typeof reader.result === "string" ? reader.result : "");
    };
    reader.onerror = () => setSaveError("The photo could not be read.");
    reader.readAsDataURL(file);
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!profile) return;
    setIsSaving(true);
    setSaveMessage(null);
    setSaveError(null);
    try {
      const result = await saveFacultyProfile(userId, profile);
      setStorage(result.storage);
      setSaveMessage(result.message);
      setNotice(
        result.storage === "server"
          ? null
          : "Profile saved on this device. The backend has no profile write endpoint yet."
      );
    } catch (err: unknown) {
      setSaveError(err instanceof Error ? err.message : "The profile could not be saved.");
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24 text-[#77735F]">
        <div className="w-7 h-7 border-2 border-[#3F451F] border-t-transparent rounded-full animate-spin" />
        <span className="ml-3 text-sm font-medium">Loading your faculty profile…</span>
      </div>
    );
  }

  if (loadError || !profile) {
    return (
      <div className="max-w-2xl mx-auto space-y-4">
        <div className="p-5 rounded-2xl bg-rose-50 border border-rose-200 text-rose-800 text-sm">
          {loadError || "The faculty profile could not be loaded."}
        </div>
        <button
          type="button"
          onClick={() => void loadProfile()}
          className="px-4 py-2 rounded-xl bg-[#3F451F] text-[#EDE8D8] text-xs font-bold cursor-pointer"
        >
          Try again
        </button>
      </div>
    );
  }

  const inputClass =
    "w-full px-3.5 py-2.5 rounded-xl bg-white border border-[#E4DDCA] text-sm text-[#24251C] placeholder-[#77735F]/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119] transition-all";
  const labelClass = "block text-xs font-bold text-[#24251C] mb-1.5";

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-[#24251C] tracking-tight">
            My Profile
          </h1>
          <p className="text-xs sm:text-sm text-[#77735F] mt-1">
            Your faculty identity, academic profile and subject expertise.
          </p>
        </div>
        <span
          className={`self-start px-3 py-1.5 rounded-xl text-[10px] font-black uppercase tracking-wider ${
            isAdmin
              ? "bg-[#6C5119] text-[#EDE8D8]"
              : "bg-[#3F451F] text-[#EDE8D8]"
          }`}
        >
          {isAdmin ? "Institution Admin" : "Teacher / Faculty"}
        </span>
      </div>

      {/* Storage notice */}
      {notice && (
        <div className="p-3.5 rounded-xl bg-amber-50 border border-amber-200 text-xs text-amber-900 flex items-start gap-2">
          <svg className="w-4 h-4 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span>{notice}</span>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Identity card */}
        <section className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-5 sm:p-6 shadow-2xs">
          <div className="flex flex-col sm:flex-row sm:items-center gap-5">
            <div className="flex items-center gap-4">
              <div className="h-24 w-24 shrink-0 rounded-full overflow-hidden bg-[#3F451F] text-[#EDE8D8] flex items-center justify-center font-black text-3xl ring-4 ring-[#EDE8D8]">
                {profile.photoUrl ? (
                  <img
                    src={profile.photoUrl}
                    alt={`${profile.fullName || "Faculty"} profile photo`}
                    className="h-full w-full object-cover"
                  />
                ) : (
                  (profile.fullName || profile.facultyId || "U").charAt(0).toUpperCase()
                )}
              </div>
              <div className="space-y-2">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={handlePhotoChange}
                />
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="px-3 py-1.5 rounded-xl bg-white border border-[#E4DDCA] text-xs font-bold text-[#24251C] hover:bg-[#EDE8D8]/60 transition-colors cursor-pointer"
                >
                  {profile.photoUrl ? "Change photo" : "Upload photo"}
                </button>
                {profile.photoUrl && (
                  <button
                    type="button"
                    onClick={() => update("photoUrl", "")}
                    className="block px-3 py-1.5 text-xs font-semibold text-rose-700 hover:underline cursor-pointer"
                  >
                    Remove photo
                  </button>
                )}
                <p className="text-[10px] text-[#77735F] max-w-[160px]">
                  PNG or JPG, up to 2 MB. Stored with the rest of your profile.
                </p>
              </div>
            </div>

            <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className={labelClass} htmlFor="fullName">
                  Full name
                </label>
                <input
                  id="fullName"
                  className={inputClass}
                  value={profile.fullName}
                  onChange={(e) => update("fullName", e.target.value)}
                  placeholder="e.g. Dr. Ananya Sharma"
                />
              </div>
              <div>
                <label className={labelClass} htmlFor="mobile">
                  Mobile number
                </label>
                <input
                  id="mobile"
                  inputMode="tel"
                  className={inputClass}
                  value={profile.mobile}
                  onChange={(e) => update("mobile", e.target.value)}
                  placeholder="e.g. +91 98765 43210"
                />
              </div>
              <div>
                <label className={labelClass} htmlFor="email">
                  Email address
                </label>
                <input
                  id="email"
                  type="email"
                  className={inputClass}
                  value={profile.email}
                  onChange={(e) => update("email", e.target.value)}
                  placeholder="name@institution.edu"
                />
                <p className="mt-1 text-[10px] text-[#77735F]">
                  The signed-in account email is{" "}
                  <span className="font-mono">{session?.userId || "—"}</span>. Changing the
                  display email here does not change the login credential.
                </p>
              </div>
              <div>
                <label className={labelClass} htmlFor="branch">
                  Branch / department
                </label>
                <input
                  id="branch"
                  className={inputClass}
                  value={profile.branch}
                  onChange={(e) => update("branch", e.target.value)}
                  placeholder="e.g. Computer Science & Engineering"
                />
              </div>
              <div>
                <label className={labelClass} htmlFor="facultyId">
                  Faculty ID
                </label>
                <input
                  id="facultyId"
                  className={`${inputClass} bg-[#F2EDE0] text-[#77735F]`}
                  value={profile.facultyId || session?.userId || ""}
                  readOnly
                />
                <p className="mt-1 text-[10px] text-[#77735F]">
                  The faculty identifier is the account id issued by the backend.
                </p>
              </div>
              <div>
                <label className={labelClass} htmlFor="designation">
                  Designation
                </label>
                <select
                  id="designation"
                  className={`${inputClass} cursor-pointer`}
                  value={profile.designation}
                  onChange={(e) =>
                    update("designation", e.target.value as FacultyProfile["designation"])
                  }
                >
                  <option value="">Select a designation</option>
                  {DESIGNATIONS.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className={labelClass} htmlFor="experience">
                  Years of experience
                </label>
                <input
                  id="experience"
                  type="number"
                  min={0}
                  max={70}
                  className={inputClass}
                  value={profile.experienceYears ?? ""}
                  onChange={(e) =>
                    update(
                      "experienceYears",
                      e.target.value === "" ? null : Number(e.target.value)
                    )
                  }
                  placeholder="e.g. 8"
                />
              </div>
              <div>
                <label className={labelClass} htmlFor="qualifications">
                  Academic qualifications
                </label>
                <input
                  id="qualifications"
                  className={inputClass}
                  value={profile.qualifications}
                  onChange={(e) => update("qualifications", e.target.value)}
                  placeholder="e.g. Ph.D. Computer Science, M.Tech Information Security"
                />
              </div>
              <div className="sm:col-span-2">
                <label className={labelClass} htmlFor="specialization">
                  Specialization
                </label>
                <input
                  id="specialization"
                  className={inputClass}
                  value={profile.specialization}
                  onChange={(e) => update("specialization", e.target.value)}
                  placeholder="e.g. Applied Cryptography & Network Security"
                />
              </div>
            </div>
          </div>
        </section>

        {/* Expertise */}
        <section className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-5 sm:p-6 shadow-2xs space-y-5">
          <div>
            <h2 className="text-base font-bold text-[#24251C]">Subject expertise</h2>
            <p className="text-xs text-[#77735F] mt-0.5">
              Manage the areas you teach. The suggestions below are examples - nothing is
              assigned automatically.
            </p>
          </div>

          {(
            [
              {
                kind: "expertise" as TagInput,
                title: "Expertise areas",
                placeholder: "Add an expertise area, e.g. Cryptography",
                suggestions: EXPERTISE_SUGGESTIONS,
              },
              {
                kind: "masteredSubjects" as TagInput,
                title: "Maintained subjects",
                placeholder: "Add a subject, e.g. DIST-SYS",
                suggestions: assignedSubjects,
              },
            ] as const
          ).map((block) => (
            <div key={block.kind} className="space-y-2.5">
              <p className="text-xs font-bold text-[#24251C]">{block.title}</p>
              <div className="flex flex-col sm:flex-row gap-2">
                <input
                  className={inputClass}
                  value={tagDraft[block.kind]}
                  onChange={(e) =>
                    setTagDraft((prev) => ({ ...prev, [block.kind]: e.target.value }))
                  }
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      addTag(block.kind);
                    }
                  }}
                  placeholder={block.placeholder}
                />
                <button
                  type="button"
                  onClick={() => addTag(block.kind)}
                  className="px-4 py-2.5 rounded-xl bg-[#3F451F] text-[#EDE8D8] text-xs font-bold hover:bg-[#343919] transition-colors cursor-pointer whitespace-nowrap"
                >
                  Add
                </button>
              </div>

              {profile[block.kind].length > 0 && (
                <div className="flex flex-wrap gap-2 pt-1">
                  {profile[block.kind].map((tag) => (
                    <span
                      key={tag}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-[#EDE8D8] px-2.5 py-1 text-xs font-semibold text-[#3F451F] border border-[#E4DDCA]"
                    >
                      {tag}
                      <button
                        type="button"
                        onClick={() => removeTag(block.kind, tag)}
                        aria-label={`Remove ${tag}`}
                        className="text-[#77735F] hover:text-rose-700 cursor-pointer"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              )}

              {block.suggestions.length > 0 && (
                <div className="flex flex-wrap items-center gap-2 pt-1">
                  <span className="text-[10px] font-black uppercase tracking-wider text-[#77735F]">
                    {block.kind === "expertise" ? "Suggestions" : "Your assigned codes"}
                  </span>
                  {block.suggestions.map((suggestion) => (
                    <button
                      key={suggestion}
                      type="button"
                      onClick={() => {
                        if (!profile) return;
                        if (
                          profile[block.kind].some(
                            (item) => item.toLowerCase() === suggestion.toLowerCase()
                          )
                        ) {
                          return;
                        }
                        update(block.kind, [...profile[block.kind], suggestion]);
                      }}
                      className="px-2 py-1 rounded-lg bg-white border border-dashed border-[#E4DDCA] text-[11px] font-semibold text-[#6C5119] hover:bg-[#EDE8D8]/50 transition-colors cursor-pointer"
                    >
                      + {suggestion}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
        </section>

        {/* Save bar */}
        <div className="sticky bottom-4 flex flex-col sm:flex-row sm:items-center gap-3 rounded-2xl bg-[#FBF8F0] border border-[#E4DDCA] p-4 shadow-lg">
          <div className="flex-1 text-xs text-[#77735F]">
            {saveMessage && <p className="text-emerald-700 font-semibold">{saveMessage}</p>}
            {saveError && <p className="text-rose-700 font-semibold">{saveError}</p>}
            {!saveMessage && !saveError && (
              <p>
                Saved profile details are stored{" "}
                <span className="font-bold text-[#24251C]">
                  {storage === "server" ? "on the RollCall AI server" : "on this device"}
                </span>
                .
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Link
              to="/settings"
              className="px-4 py-2.5 rounded-xl border border-[#E4DDCA] text-xs font-bold text-[#24251C] hover:bg-[#EDE8D8]/60 transition-colors"
            >
              Account settings
            </Link>
            <button
              type="submit"
              disabled={isSaving}
              className="px-5 py-2.5 rounded-xl bg-[#6C5119] hover:bg-[#594214] text-white text-xs font-bold shadow-2xs transition-colors disabled:opacity-50 cursor-pointer"
            >
              {isSaving ? "Saving…" : "Save profile"}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
