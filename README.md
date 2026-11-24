# Integrated AI

A small Python orchestrator that routes tasks to specialist agents and, when configured, to multiple AI providers: OpenAI, Gemini, Claude, and DeepSeek. It does not compile or merge model weights. It orchestrates calls and keeps conversation memory.

## What is implemented

- OpenAI model routing: original fast/strong routing preserved (`choose_model`, Responses API). `MODEL_FAST` default `gpt-4.1-mini`, `MODEL_STRONG` default `gpt-4.1` (set to IDs your account can use).
- Gemini integration: optional, via `GEMINI_API_KEY` (or `GOOGLE_API_KEY`), model `MODEL_GEMINI` (default `gemini-2.5-flash`).
- Claude integration: optional, via `ANTHROPIC_API_KEY`, model `MODEL_CLAUDE` (default `claude-sonnet-4-5`).
- DeepSeek integration: optional, via `DEEPSEEK_API_KEY`, model `MODEL_DEEPSEEK` (default `deepseek-chat`).
- Multiple specialist agents: `general`, `coding`, `research`, `security`, `assignment`, each with its own system prompt. Tasks auto-route to an agent; override with `AGENT` env var, `/agent` in the CLI, or the `agent` field in the API.
- Conversation memory: local JSON file (`MEMORY_FILE`, default `~/.integrated-ai/memory.json`), capped by `MEMORY_MAX_TURNS` (default 20). Stored on your device only. `/clear` or `POST /clear` clears it.
- File uploads (new): attach images and documents from the web UI, Android app, or API.
  - Images (`.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`) are sent as real image input to vision-capable models (OpenAI, Gemini, Claude). DeepSeek cannot see images.
  - Documents/text (`.pdf`, `.docx`, `.txt`, `.md`, `.py`, `.js`, `.ts`, `.json`, `.csv`, `.html`, `.sh`, `.yml`, `.yaml`, `.log`, `.xml`, `.css`, `.java`, `.c`, `.cpp`, `.go`, `.rs`, `.sql`, `.ini`, `.toml`) are text-extracted locally (stdlib-only best-effort for PDF/DOCX) and fed to the model as text.
  - ZIP archives (`.zip`): member list + text extracted in memory (zip-bomb and path-traversal protected, never written to disk).
  - Endpoints: `POST /chat` accepts optional `files: [{filename, data_b64}]`; `POST /upload/analyze` takes `{question, files, agent, provider, session_id}`; `POST /process-file` still works (now also accepts `files` or binary `content_base64`). CLI `/analyze <path>` supports the same types.
  - Validation: extension + magic bytes + size are checked. Files are never executed and never written to disk by the server.
  - Limits (configurable, generous defaults, no arbitrary low cap): `UPLOAD_MAX_BYTES` (50 MB/file), `MAX_UPLOAD_FILES` (10/request), `UPLOAD_TOTAL_MAX_BYTES` (200 MB/request), `MAX_FILE_BYTES` (200000, text-per-prompt cap). Raise them as high as your provider and server allow.
  - Honest truth about limits: raising these only raises THIS server's limits. Every AI provider has its own hard limits (context window, image size/count rules, request size caps), and the server keeps safety limits too. No app setting can remove provider limits. Practical defaults are set so normal photos, PDFs and assignments work; raise the env vars if your provider allows larger files.
  - Capability matrix: `GET /providers` returns each provider's `vision: true/false`, the supported extensions, the active limits, and notes. `GET /health` includes the limits.
  - Auto routing with images: with `provider=auto`, an image upload picks a configured vision provider (OpenAI, then Gemini, then Claude). With no vision provider configured it explains what to set instead of faking an answer. Selecting `deepseek` with an image says plainly DeepSeek cannot analyze images.
  - Android app: Attach file button picks images/documents (multi-select), Analyze files sends them to `POST /upload/analyze`. No API keys in the app, ever.
- API/backend server: `python main.py serve` starts it on `HOST:PORT` (default `0.0.0.0:8000`). Set `APP_ACCESS_TOKEN` to require `Authorization: Bearer <token>` on every endpoint except `/` and `/health`. In production, also set `APP_ENV=production`; the server refuses to start without `APP_ACCESS_TOKEN`. Basic per-IP in-memory rate limiting defaults to 60 requests per 60 seconds and is configurable with `RATE_LIMIT_MAX_REQUESTS` and `RATE_LIMIT_WINDOW_SECONDS`. The rate limiter is per process and is not a replacement for a production gateway/WAF. The browser UI and Android app provide a password field; the Android token is held only in memory and must be re-entered after restart. Use HTTPS for any remote deployment. Endpoints: `GET /`, `GET /health`, `GET /providers`, `GET /memory/sessions`, `GET /workspace/list`, `GET /workspace/download`, `POST /chat`, `POST /upload/analyze`, `POST /process-file`, `POST /workspace/save`, `POST /workspace/edit`, `POST /clear`.
- Mobile web interface: open `http://<your-computer-ip>:8000` in a browser on the same Wi-Fi. A separate native Kotlin Android client is included under `android-app/`; it connects to this Python backend.

## Setup

1. Install Python 3.10+.
2. `python -m venv .venv && source .venv/bin/activate` (Windows: `.venv\Scripts\activate`).
3. `pip install -r requirements.txt`
4. Set API keys as environment variables only. Never paste keys into source files:

   ```bash
   export OPENAI_API_KEY="..."
   export GEMINI_API_KEY="..."
   export ANTHROPIC_API_KEY="..."
   export DEEPSEEK_API_KEY="..."
   ```

   On Windows PowerShell use `$env:OPENAI_API_KEY="..."` instead of `export`.

5. Optionally override models and behavior:

   ```bash
   export MODEL_FAST="gpt-4.1-mini" MODEL_STRONG="gpt-4.1"
   export MODEL_GEMINI="gemini-2.5-flash" MODEL_CLAUDE="claude-sonnet-4-5" MODEL_DEEPSEEK="deepseek-chat"
   export PROVIDER="auto"   # or openai | gemini | claude | deepseek
   export AGENT="general"   # or coding | research | security
   export PORT="8000"
   export APP_ENV="production" APP_ACCESS_TOKEN="generate-a-long-random-token"
   export RATE_LIMIT_MAX_REQUESTS="60" RATE_LIMIT_WINDOW_SECONDS="60"
   export UPLOAD_MAX_BYTES="52428800" MAX_UPLOAD_FILES="10" UPLOAD_TOTAL_MAX_BYTES="209715200"
   ```

6. Run the CLI: `python main.py`
   Or run the server: `python main.py serve`, then open `http://localhost:8000` (or your computer's LAN IP from an Android phone).

## Missing provider keys

This scaffold includes no credentials and makes no paid calls by itself.

- If a provider has no key, the app says exactly which env var to set (for example `set GEMINI_API_KEY ...`) and sends no request to it.
- With `PROVIDER=auto` (default) it uses a configured provider if one exists, preferring OpenAI for general tasks, an agent's preferred provider (research prefers Gemini), and DeepSeek/Claude for coding tasks.
- With no keys at all, every answer explains what is missing. Nothing is faked.
- Each provider is called only when you run the app with that key set, so cost stays under your control.

## API examples

```bash
curl -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "Explain this error", "agent": "coding"}'

curl -X POST http://localhost:8000/process-file \
  -H 'Content-Type: application/json' \
  -d '{"filename": "notes.txt", "content": "...", "question": "Summarize this"}'

# image + question in one chat call (base64 the file first, e.g. `base64 -w0 photo.png`)
curl -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "What does this image show?", "files": [{"filename": "photo.png", "data_b64": "<BASE64>"}]}'

# dedicated upload analysis
curl -X POST http://localhost:8000/upload/analyze \
  -H 'Content-Type: application/json' \
  -d '{"question": "Summarize this PDF", "files": [{"filename": "doc.pdf", "data_b64": "<BASE64>"}]}'
```

## Workspace and projects

- Generated files: `POST /workspace/save {session_id, filename, content}` saves model-generated text/code into the session workspace; `POST /workspace/edit {session_id, filename, old_text, new_text}` patches a saved file; `GET /workspace/list?session_id=X` lists files; `GET /workspace/download?session_id=X&file=Y` downloads with an attachment header.
- Paths are clamped to the workspace directory (`WORKSPACE_DIR`, default `~/.integrated-ai/workspace`); traversal attempts are rejected with 404/400.
- Project conversations: use `session_id` of the form `project/<name>` (e.g. `project/my-assignment`) for persistent memory plus its own workspace folder. `GET /memory/sessions` lists sessions and turn counts. This is how coding projects, assignments, and research workspaces stay organized and resumable.
- Assignment/research help is the `assignment` agent; coding generation/editing/debugging works through the `coding` agent plus workspace save/edit endpoints.

## CLI commands

- `/agent coding|research|security|general` switch specialist
- `/provider openai|gemini|claude|deepseek|auto` switch provider
- `/analyze <path>` analyze a local text, document (pdf/docx), or image file
- `/memory` show stored turn count
- `/clear` clear memory
- `quit` / `exit` leave

## Honest limitations

- The native Android source is included, but this archive does not contain a verified APK. Build it with Android Studio or the included GitHub Actions workflow.
- File uploads are size/count limited (see the limits section above). PDF/DOCX extraction is best-effort stdlib-only text extraction: scanned/image PDFs need OCR (not included), and some PDF layouts may extract imperfectly. No vector search.
- Memory is local JSON on one device, not shared across devices or users.
- Provider integrations are basic chat completions; no streaming, tools, or function calling yet.
- Authentication is optional in development when `APP_ACCESS_TOKEN` is unset. For public hosting, set `APP_ENV=production` and a strong `APP_ACCESS_TOKEN`; the server fails closed if production mode has no token. `/` and `/health` are public for the landing page and host health checks. HTTPS is required for remote use. The built-in in-memory rate limit is a basic safeguard, not a distributed abuse-prevention system.
- Model names are configurable defaults. If a default is not available on your account, set the matching `MODEL_*` variable.

## GitHub and automated builds

Two GitHub Actions workflows are included:

- `Backend tests` runs `python tests/test_uploads.py` on pushes and pull requests.
- `Android debug APK` builds the Kotlin app with Java 17, Android SDK 34 and Gradle 8.7. The APK is uploaded as a workflow artifact named `integrated-ai-debug-apk`.

To use them, upload the contents of this `integrated-ai/` folder to the root of a GitHub repository. Push to `main` or `master`, then open the repository's **Actions** tab. After the Android workflow succeeds, open its run and download the APK artifact.

## Security warning before deployment

The Python HTTP backend currently has **no authentication**. Do not expose it directly to the public internet or deploy it as a public service. Keep it on a trusted local network for development until authentication, HTTPS, rate limiting, and production configuration are added. API keys must remain in server-side environment variables and must never be committed.
