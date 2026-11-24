# Image upload / extraction latency

The "Uploading the roster… 0%" screen was caused by two separate problems.

## What was slow

1. **Unbounded, sequential Gemini calls.** Form-B scans tried up to four model
   names through the modern SDK and then repeated all four through the legacy
   SDK — eight network calls with no per-call timeout. Every image upload also
   made an extra Gemini classifier call before extraction.
2. **Blocking the event loop.** `/api/v1/agent/process-file` is an `async def`
   endpoint that called synchronous OCR/Vision code directly, so one slow photo
   stalled unrelated requests.
3. **Misleading progress.** Axios does not always report `event.total` for
   multipart uploads; the UI computed `0 / 0` and displayed `0%` for the whole
   request.

## Changes

| Area | Change |
| --- | --- |
| `backend/app/services/vision_client.py` | Shared Gemini client with `VISION_TIMEOUT_MS` (default 20s) and a single attempt. |
| `backend/app/services/exam_vision.py` | At most two model attempts, legacy SDK only when the modern one is unavailable, and a timing log for successful scans. |
| `backend/app/agent/legacy_agent.py` | Form-B classification now uses local OCR first and calls Gemini only when OCR is inconclusive; all vision clients are time-bounded; model loops capped at two. |
| `backend/app/routers/agent.py` | Vision extraction runs in a worker thread (`run_in_threadpool`), keeping the API responsive during processing. |
| `frontend-react/src/services/api/agent.ts` | Upload progress falls back to `File.size`; unknown totals are reported as indeterminate (`-1`). |
| `frontend-react/src/features/assistant/AssistantView.tsx` | Indeterminate state shows "Sending the roster…" with an animated bar instead of a stuck `0%`. |

## Tuning

Set `VISION_TIMEOUT_MS` in `.env` (milliseconds, 5000–120000). Lower values fail
faster when a model is throttled; higher values suit slow networks. The value
is clamped to safe bounds.

## Photo quality gate

A sharp white Form-B sheet measured ~233 brightness was rejected because the
upper brightness ceiling was too tight (225 on the affected deployment). The
ceiling is now 250 by default (`IMAGE_QUALITY_MAX_BRIGHTNESS`) and a sharp but
overexposed upload is automatically exposure-normalised once before the Vision
call instead of forcing a retake. The response also carries
`brightness_max_threshold`, and the UI now displays the acceptable range rather
than a misleading "minimum ≥ 80".

## Verification

- `backend/tests/test_vision_timeout.py` — timeout defaults, overrides and
  clamping; model-attempt cap.
- `backend/tests/test_exams.py` — mocked Form-B scan and exam routes pass.
- `frontend-react`: `tsc -b` and `vite build` pass.
