# Integrated AI

Integrated AI is a Gemini-powered Android AI assistant with a Python backend. It uses one provider (Google Gemini) and specialist modes to adapt its instructions to the task.

## Gemini configuration

Set these variables in your hosting provider (Railway):

- `GEMINI_API_KEY` — required secret.
- `MODEL_GEMINI` — optional model ID; defaults to `gemini-2.5-flash`.
- `APP_ENV=production` and `APP_ACCESS_TOKEN` — required for a protected public deployment.
- `PORT` — supplied by Railway.

Never put the Gemini API key in the Android app, GitHub, or a source file. Keep it in Railway's private Variables panel.

## Specialist modes

The app sends every request to Gemini. The selected mode changes the system instructions:

- General
- Coding
- Research
- Security
- Assignment
- Study
- Arabic (Nahw, Sarf and I'rab)
- Math
- Writing

These modes are task-specific instructions, not separate models. They do not increase the underlying model's intelligence or remove its API quotas.

## Features

- Gemini text and image input.
- Text extraction from PDF, DOCX, TXT, Markdown, CSV, JSON, HTML and source-code files.
- ZIP inspection with path-traversal and archive-size protections.
- Per-session conversation history.
- Project sessions using IDs such as `project/my-project`.
- Workspace save, list, edit and download endpoints.
- Android chat interface with specialist modes and multi-file attachment support.
- Bearer-token authentication for protected backend endpoints.

## Run locally

1. Install Python 3.10 or later.
2. Set `GEMINI_API_KEY` in your environment.
3. Optionally set `APP_ENV=production` and `APP_ACCESS_TOKEN`.
4. Run `python main.py serve`.

The server listens on `0.0.0.0:$PORT` (default port 8000).

## API

- `GET /` — lightweight browser tester.
- `GET /health` — public health check.
- `GET /providers` — Gemini configuration and capability information (requires auth in production).
- `POST /chat` — send a message; all requests route to Gemini.
- `POST /upload/analyze` — analyse uploaded files with Gemini.
- `GET /memory/sessions` — list session summaries.
- `GET /workspace/list`, `GET /workspace/download`.
- `POST /workspace/save`, `POST /workspace/edit`, `POST /clear`.

## Important limitations

- Gemini API quotas, model availability, safety rules, context limits and rate limits still apply. App-side changes cannot bypass them.
- Free-tier availability and limits depend on Google's current terms, model and region.
- This backend does not currently perform live web search or guarantee source citations.
- PDF/DOCX extraction is best-effort; scanned PDFs need OCR, which is not included.
- Conversation memory and workspace files need a persistent Railway volume to survive service replacement/redeployment. Without one, local container storage may be temporary.
- Specialist modes improve task framing and answer structure; they are not independent expert models.

## Tests and Android build

The GitHub Actions workflows run backend tests and build a debug Android APK. A successful build verifies compilation, not all on-device runtime behavior. Install and test on a physical Android device before treating the release as complete.
