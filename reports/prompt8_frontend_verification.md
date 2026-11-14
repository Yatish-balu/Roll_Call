# Prompt 8 — Verification sweep (frontend fixes, backend, blank screen)

Date: 2026-11-14  
Branch: `kk` (HEAD `4fa8d62e`; working tree also contains the Settings cache refactor)  
App: React + Vite frontend (`Roll_Call/frontend-react`), FastAPI backend (`Roll_Call/backend`)  
Frontend URL: `http://127.0.0.1:5173` · API: `http://127.0.0.1:8000`

## TL;DR

- The reported **blank screen** was reproducible only while the in-progress
  `SettingsView` cache refactor still referenced removed state setters
  (`setMetaConfig`, `setSessions`, `loadSessions`, `setIsCheckingHealth`).
  Vite logged module-transform `500`s and the browser logged
  `ReferenceError`s, which aborted the render. After completing the refactor the
  app compiles and every route renders.
- Backend: **775 passed, 1 skipped** (`pytest -q`).
- Frontend: `tsc --noEmit` **0**, `eslint .` **0**, `vite build` **0**
  (only the pre-existing >500 kB chunk-size warning).
- Headless Chrome (CDP), fresh profile: **10/10 pages render**; warm tab
  switches make **0 API calls**; theme toggle persists across reload; password
  visibility toggles switch `password` ↔ `text`; `/profile` renders. No console
  errors after login (only the expected `401` from the pre-login silent-refresh
  probe).

## Command results

| Check | Command | Result |
|---|---|---|
| Backend tests | `cd backend; python -m pytest -q` | `775 passed, 1 skipped in 174.67s` |
| Type check | `cd frontend-react; npx tsc --noEmit` | exit 0 |
| Lint | `cd frontend-react; npm run lint` | exit 0 |
| Production build | `cd frontend-react; npm run build` | exit 0, `dist/assets/index-*.js 656.29 kB` (warning only) |
| Browser smoke | CDP script against a fresh Chrome profile | all assertions below |

## Reported issues → fix → verification

| # | Reported issue / area | Fix location | Verified by |
|---|---|---|---|
| 1 | Database access / connection handling (Supabase-only runtime) | `backend/app/db/connection.py`, pooled SQLAlchemy sessions | Backend suite green; live `/health` + `/auth/me` + `/me/profile` against Supabase |
| 2 | Login / dashboard N+1 and slow queries | `backend/app/db/crud.py`, `backend/app/routers/auth.py`, `alembic/versions/0018_performance_indexes.py` | `pytest` suite; indexes present at head `0019_user_profiles` |
| 3 | Faculty profile settings not persisting | `backend/app/routers/me.py`, `backend/app/schemas/profile.py`, `alembic/versions/0019_user_profiles.py`, `frontend-react/src/services/api/profile.ts` | `backend/tests/test_me_profile.py` 5/5; PATCH persists across re-login and a direct DB read |
| 4 | Dashboard / sessions / students loading data twice | `DashboardView`, `SessionsView`, `StudentsView`, `hooks/useResource.ts`, `services/api/cache.ts` | CDP: cold visit issues one request per endpoint; warm visit issues none |
| 5 | Slow tab navigation (full refetch on every tab switch) | `frontend-react/src/services/api/cache.ts` (SWR store, 60 s stale time, key-prefix invalidation), `frontend-react/src/hooks/useResource.ts`, all feature views | CDP warm round-trips: `settingsWarmRequests: []`, `studentsWarmRequests: []`, `dashboardWarmRequests: []`, `sessionsWarmRequests: []` |
| 6 | Password visibility eye buttons inconsistent | `frontend-react/src/components/auth/LoginView.tsx`, `frontend-react/src/features/settings/SettingsView.tsx` | CDP: `#oldPassword` type `password` → `text` → `password`; all toggles are `type="button"`, functional `setShow…((prev) => !prev)`, icons `pointer-events-none` |
| 7 | Appearance theme toggle does nothing / resets on reload | `frontend-react/src/index.css` (`@custom-variant dark`), `src/lib/preferences.ts` (`applyTheme`), `src/main.tsx`, `index.html` (anti-flash inline script), `SettingsView` Appearance card | CDP: click **Dark** → `dataset.theme="dark"`, `.dark` class present, `localStorage.rollcall.pref.all.theme="dark"`; full reload keeps dark; restored to warm afterwards |
| 8 | No consolidated regression evidence; reported blank screen | This report; `SettingsView` refactor completed | Backend + frontend + browser checks above |

### Blank-screen root cause (detail)

While `SettingsView` was mid-refactor, the dev server pushed a module whose
handlers still called `setMetaConfig`, `setSessions`/`loadSessions`, and
`setIsCheckingHealth` after those declarations were removed. Vite returned
`500` for the module transform and React threw `ReferenceError` on mount, so
`#root` stayed empty. The refactor is now complete:

- `meta/config`, `auth/mfa/status`, `auth/sessions`, and `health` are read via
  `useResource` (cached, deduplicated, revalidated only when stale).
- Revoke / MFA verify / MFA disable call `invalidate(...)` on the affected key
  instead of imperatively reloading.
- The "Refresh sessions" / "Test server connection" buttons call the hook's
  `refresh()`.

A fresh headless session confirms the login screen, every sidebar route, and the
profile route all render.

## Browser verification steps (manual)

1. Open `http://127.0.0.1:5173` (not `:8000` — that is the API only). The login
   screen must paint immediately.
2. Sign in as `faculty_cn` / `FacultyPass_CN_2026!`.
3. Open DevTools → Network, filter `students`. Click **Students**, go to
   **Dashboard**, then back to **Students**. Only the first visit should issue
   `/api/v1/students` and `/api/v1/reports/students/filters`; the second is
   served from cache.
4. **Settings → Appearance → Dark**: `<html>` gains `class="dark"` and
   `data-theme="dark"`; the page switches to dark surfaces. Reload — it stays
   dark. Choose **System** to follow the OS.
5. **Settings → Change password**: each eye button toggles only its own field
   between masked and plain text and must not submit the form.
6. Open `/profile` directly (or from the sidebar/avatar). The profile form
   renders; change the designation and save; reload or sign out/in and confirm
   the value is still there.
7. Return to **Settings** within 60 s: Network should show no repeat of
   `/api/v1/meta/config`, `/api/v1/auth/mfa/status`, or `/api/v1/auth/sessions`.

## Files touched in this pass

- `frontend-react/src/features/settings/SettingsView.tsx` (unstaged):
  cached `meta/config`, `mfa/status`, `auth/sessions`, and `health`; mutation
  handlers now `invalidate(...)`; refresh buttons use `refresh()`; sessions
  error surfaces the hook error.
- Committed previously (HEAD `4fa8d62e`, commit `8ce5dbe7` "apply prompts 5-7"):
  `services/api/cache.ts`, `hooks/useResource.ts`, all feature views,
  `index.css`, `lib/preferences.ts`, `main.tsx`, `index.html`,
  `LoginView.tsx`, plus the prompts 1–4 backend work in `e0b1de97`
  (`db/connection.py`, `db/crud.py`, migrations `0018`/`0019`, `routers/me.py`,
  `schemas/profile.py`, `tests/test_me_profile.py`).

## Notes / caveats

- **Interpreter:** the project `venv` currently has `starlette 1.9.0`, whose
  `TestClient` requires `httpx2`, but `httpx2`/`pytest-timeout` are not
  installed there, so `venv\Scripts\python.exe -m pytest` fails at collection.
  The suite above was run with the system interpreter
  (`C:\Users\yatis\python.exe`, FastAPI 0.136.1 / Starlette 1.0.0 / httpx
  0.28.1). Install `httpx2` + `pytest-timeout` into the venv (or recreate it
  from `backend/requirements.txt`) to run tests there.
- **Bundle size:** `index-*.js` is 656 kB (176 kB gzip). Vite warns about the
  500 kB chunk limit; behaviour is unaffected. Code-splitting per route is the
  follow-up if desired.
- **Supabase password rotation** is still a manual Dashboard action, then update
  `DATABASE_URL_SYNC` in `Roll_Call/.env`.
- The pre-login `401` on `/api/v1/auth/refresh` is expected: it is the silent
  refresh attempt when no refresh session exists yet. It disappears after login.