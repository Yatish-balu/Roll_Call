import { apiClient } from "@/services/api/client";

/**
 * Faculty profile access.
 *
 * The authoritative identity fields (user id, email, role, assigned subject
 * codes) come from the real backend endpoint `GET /api/v1/auth/me`.
 *
 * The backend does not currently expose an endpoint that stores the
 * descriptive faculty profile (designation, experience, specialisation,
 * expertise tags, photo). The client therefore:
 *   1. tries the documented server contract (`GET/PUT /api/v1/profile`), and
 *   2. falls back to a clearly labelled, device-local store so the faculty can
 *      still maintain the information.
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
      serverProfile = await apiClient.get<Partial<FacultyProfile>>("/api/v1/profile");
      serverProfileSupported = true;
    } catch {
      serverProfileSupported = false;
      serverProfile = null;
    }
  }

  const local = readLocalProfile(userId);

  if (serverProfile) {
    return {
      authoritative,
      profile: { ...EMPTY_PROFILE, ...local, ...serverProfile },
      storage: "server",
      notice,
    };
  }

  if (!notice) {
    notice =
      "Designation, experience, qualifications, specialisation and expertise are stored on this device. " +
      "The RollCall AI backend does not expose a profile write endpoint yet.";
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
}

/**
 * Persist the faculty profile. The server contract is attempted first; when
 * the backend does not implement it the profile is stored on the device and the
 * caller is told which storage was used.
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
        "Profile saved on this device. The backend has no profile write endpoint yet, so the details were not sent to the server.",
    };
  }

  try {
    await apiClient.put<unknown>("/api/v1/profile", profile);
    serverProfileSupported = true;
    return {
      storage: "server",
      message: "Profile saved on the RollCall AI server.",
    };
  } catch {
    serverProfileSupported = false;
    writeLocalProfile(userId, profile);
    return {
      storage: "device",
      message:
        "Profile saved on this device. The backend has no profile write endpoint yet, so the details were not sent to the server.",
    };
  }
}
