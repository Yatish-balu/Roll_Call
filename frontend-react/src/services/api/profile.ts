import { ApiError, apiClient } from "@/services/api/client";

/**
 * Faculty profile access.
 *
 * The authoritative identity fields (user id, display name, email, role) come
 * from `GET /api/v1/auth/me`; the descriptive faculty profile (designation,
 * experience, specialisation, expertise tags, photo) is persisted on the
 * backend via `GET/PUT/PATCH /api/v1/me/profile` (camelCase FacultyProfile
 * contract). A device-local mirror keeps the last known values so the UI can
 * still render offline; the server response always wins when it is available.
 *
 * The UI always shows which storage was used - it never pretends that a value
 * was saved on the server when it was not.
 */

export interface AuthenticatedProfile {
  user_id: string;
  email: string;
  role: string;
  is_active: number;
  subject_codes: string[];
}

export const DESIGNATIONS = [
  "Professor",
  "Associate Professor",
  "Assistant Professor",
  "Senior Assistant Professor",
  "Lecturer",
  "Other",
] as const;

export type Designation = (typeof DESIGNATIONS)[number];

/** Example expertise areas offered as suggestions - never pre-selected. */
export const EXPERTISE_SUGGESTIONS = [
  "Cyber Security",
  "Network Security",
  "Ethical Hacking",
  "Cryptography",
  "Cloud Security",
  "Computer Networks",
  "Operating Systems",
  "AI",
];

export interface FacultyProfile {
  fullName: string;
  mobile: string;
  email: string;
  branch: string;
  facultyId: string;
  designation: Designation | "";
  experienceYears: number | null;
  qualifications: string;
  specialization: string;
  expertise: string[];
  masteredSubjects: string[];
  photoUrl: string;
}

export const EMPTY_PROFILE: FacultyProfile = {
  fullName: "",
  mobile: "",
  email: "",
  branch: "",
  facultyId: "",
  designation: "",
  experienceYears: null,
  qualifications: "",
  specialization: "",
  expertise: [],
  masteredSubjects: [],
  photoUrl: "",
};

export type ProfileStorage = "server" | "device";

export interface ProfileLoadResult {
  authoritative: AuthenticatedProfile | null;
  profile: FacultyProfile;
  storage: ProfileStorage;
  notice: string | null;
}

const LOCAL_STORAGE_KEY = "rollcall.profile.v1";

function storageKey(userId: string): string {
  return `${LOCAL_STORAGE_KEY}.${userId || "anonymous"}`;
}

function readLocalProfile(userId: string): FacultyProfile {
  if (typeof window === "undefined") return { ...EMPTY_PROFILE };
  try {
    const raw = window.localStorage.getItem(storageKey(userId));
    if (!raw) return { ...EMPTY_PROFILE };
    const parsed = JSON.parse(raw) as Partial<FacultyProfile>;
    return {
      ...EMPTY_PROFILE,
      ...parsed,
      expertise: Array.isArray(parsed.expertise) ? parsed.expertise : [],
      masteredSubjects: Array.isArray(parsed.masteredSubjects) ? parsed.masteredSubjects : [],
    };
  } catch {
    return { ...EMPTY_PROFILE };
  }
}

function writeLocalProfile(userId: string, profile: FacultyProfile): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(storageKey(userId), JSON.stringify(profile));
  } catch {
    // Storage unavailable - the caller keeps the in-memory value for this session.
  }
}

export async function fetchAuthenticatedProfile(): Promise<AuthenticatedProfile> {
  return apiClient.get<AuthenticatedProfile>("/api/v1/auth/me");
}

/**
 * Load the faculty profile: authoritative identity from the backend plus the
 * descriptive profile from the server when available, otherwise from the
 * device-local store.
 */
/**
 * Cached capability flag: the server profile endpoint is probed once per
 * session so the UI does not repeat a failing request on every render.
 */
let serverProfileSupported: boolean | null = null;

export async function loadFacultyProfile(userId: string): Promise<ProfileLoadResult> {
  let authoritative: AuthenticatedProfile | null = null;
  let notice: string | null = null;

  try {
    authoritative = await fetchAuthenticatedProfile();
  } catch (err: unknown) {
    notice =
      err instanceof Error
        ? `The account details could not be loaded from the server: ${err.message}`
        : "The account details could not be loaded from the server.";
  }

  let serverProfile: Partial<FacultyProfile> | null = null;
  if (serverProfileSupported !== false) {
    try {
      serverProfile = await apiClient.get<Partial<FacultyProfile>>("/api/v1/me/profile");
      serverProfileSupported = true;
    } catch {
      serverProfileSupported = false;
      serverProfile = null;
    }
  }

  const local = readLocalProfile(userId);

  if (serverProfile) {
    const merged = { ...EMPTY_PROFILE, ...local, ...serverProfile };
    // Keep the device mirror in sync with the authoritative server copy.
    writeLocalProfile(userId, merged);
    return {
      authoritative,
      profile: merged,
      storage: "server",
      notice,
    };
  }

  if (!notice) {
    notice =
      "Designation, experience, qualifications, specialisation and expertise could not be loaded " +
      "from the server; showing the values stored on this device.";
  }

  return {
    authoritative,
    profile: {
      ...local,
      email: local.email || authoritative?.email || "",
      facultyId: local.facultyId || authoritative?.user_id || "",
      fullName: local.fullName || authoritative?.user_id || "",
    },
    storage: "device",
    notice,
  };
}

export interface ProfileSaveResult {
  storage: ProfileStorage;
  message: string;
  /** The profile as confirmed by the server when storage === "server". */
  profile?: FacultyProfile;
}

/**
 * Persist the faculty profile to the backend (`PUT /api/v1/me/profile`), then
 * mirror the server-confirmed values to the device store. When the backend is
 * unreachable the profile is stored on the device and the caller is told
 * which storage was used.
 */
export async function saveFacultyProfile(
  userId: string,
  profile: FacultyProfile
): Promise<ProfileSaveResult> {
  if (serverProfileSupported === false) {
    writeLocalProfile(userId, profile);
    return {
      storage: "device",
      message:
        "Profile saved on this device. The backend could not be reached, so the changes were not confirmed on the server.",
    };
  }

  try {
    const saved = await apiClient.put<Partial<FacultyProfile>>(
      "/api/v1/me/profile",
      profile
    );
    serverProfileSupported = true;
    const confirmed: FacultyProfile = { ...profile, ...saved };
    writeLocalProfile(userId, confirmed);
    return {
      storage: "server",
      message: "Profile saved on the RollCall AI server.",
      profile: confirmed,
    };
  } catch (err: unknown) {
    // A validation problem (422) or a taken email (409) must not silently
    // demote to device storage: surface the server's message instead.
    if (err instanceof ApiError && (err.statusCode === 422 || err.statusCode === 409)) {
      throw new Error(extractServerErrorMessage(err) || "The server rejected the profile changes.");
    }
    serverProfileSupported = false;
    writeLocalProfile(userId, profile);
    return {
      storage: "device",
      message:
        "Profile saved on this device. The backend could not be reached, so the changes were not confirmed on the server.",
    };
  }
}

/**
 * Pull a human-readable message out of the backend error body, covering both
 * custom `{detail: {error: {message}}}` responses and FastAPI validation
 * arrays (`detail: [{msg: "..."}]`).
 */
function extractServerErrorMessage(err: ApiError): string | null {
  const body = err.details as { detail?: unknown } | undefined;
  const detail = body?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const d = detail as { error?: { message?: string }; message?: string; msg?: string };
    if (d.error?.message) return d.error.message;
    if (d.message) return d.message;
    if (d.msg) return d.msg;
  }
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string };
    if (first?.msg) return first.msg;
  }
  return null;
}
