"""Integrated AI orchestrator (scaffold).

Routes each task to a specialist agent and, if configured, to a provider:
OpenAI (original routing, preserved), Gemini, Claude, or DeepSeek.

No provider is called without its own API key. Missing keys are reported
plainly; nothing is faked. All keys and model names come from environment
variables only, never from source.

Run modes:
  python main.py            CLI chat
  python main.py serve      API/backend server + Android-friendly web UI

CLI commands:
  /agent coding|research|security|general   switch specialist
  /provider openai|gemini|claude|deepseek|auto
  /analyze <path>           read a local text/image/document file and ask about it
  /memory                   show turn count
  /clear                    clear this session's memory
  quit / exit

Environment variables (all optional, see README.md):
  OPENAI_API_KEY, GEMINI_API_KEY, ANTHROPIC_API_KEY, DEEPSEEK_API_KEY
  MODEL_FAST, MODEL_STRONG, MODEL_GEMINI, MODEL_CLAUDE, MODEL_DEEPSEEK
  PROVIDER (auto|openai|gemini|claude|deepseek), AGENT (coding|research|...)
  PORT (default 8000), HOST (default 0.0.0.0)
  MEMORY_FILE, MEMORY_MAX_TURNS (default 20), MAX_FILE_BYTES (default 200000)
  UPLOAD_MAX_BYTES (default 50 MB per file), MAX_UPLOAD_FILES (10 per request),
  UPLOAD_TOTAL_MAX_BYTES (200 MB total per request). All configurable; provider limits still apply.
  WORKSPACE_DIR: where generated files are saved for download (default ~/.integrated-ai/workspace).
  Sessions like "project/<name>" give persistent project conversations with their own workspace.
  Uploads: images (jpg/jpeg/png/gif/webp) are sent to vision-capable providers;
  pdf/docx/txt/md/csv/json/html/code/log are text-extracted. PDF/docx extraction
  is stdlib-only best-effort. See README.md for provider capability matrix.
  No limit in this app can remove a provider's own size/model limits.
"""

import base64
import binascii
import io
import json
import os
import hmac
import threading
import time
import re
import zipfile
import zlib
import html as _html
import xml.etree.ElementTree as ET
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# --------------------------------------------------------------------------
# Config (environment only, no credentials in source)
# --------------------------------------------------------------------------

OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")

# Original OpenAI routing, preserved. Set to model IDs your account can use.
FAST_MODEL = os.getenv("MODEL_FAST", "gpt-4.1-mini")
STRONG_MODEL = os.getenv("MODEL_STRONG", "gpt-4.1")
MODEL_GEMINI = os.getenv("MODEL_GEMINI", "gemini-2.5-flash")
MODEL_CLAUDE = os.getenv("MODEL_CLAUDE", "claude-sonnet-4-5")
MODEL_DEEPSEEK = os.getenv("MODEL_DEEPSEEK", "deepseek-chat")

PROVIDER_OVERRIDE = os.getenv("PROVIDER", "auto").lower()
AGENT_OVERRIDE = os.getenv("AGENT", "general").lower()
MEMORY_FILE = os.getenv("MEMORY_FILE", str(Path.home() / ".integrated-ai" / "memory.json"))
MEMORY_MAX_TURNS = int(os.getenv("MEMORY_MAX_TURNS", "20"))
MAX_FILE_BYTES = int(os.getenv("MAX_FILE_BYTES", "200000"))
UPLOAD_MAX_BYTES = int(os.getenv("UPLOAD_MAX_BYTES", "52428800"))  # 50 MB per file (configurable)
MAX_UPLOAD_FILES = int(os.getenv("MAX_UPLOAD_FILES", "10"))
UPLOAD_TOTAL_MAX_BYTES = int(os.getenv("UPLOAD_TOTAL_MAX_BYTES", "209715200"))  # 200 MB total per request
WORKSPACE_DIR = os.getenv("WORKSPACE_DIR", str(Path.home() / ".integrated-ai" / "workspace"))
MAX_ZIP_MEMBERS = int(os.getenv("MAX_ZIP_MEMBERS", "200"))
MAX_ZIP_UNCOMPRESSED_BYTES = int(os.getenv("MAX_ZIP_UNCOMPRESSED_BYTES", "209715200"))
MAX_REQUEST_BYTES = int(UPLOAD_TOTAL_MAX_BYTES * 1.4 + 1024 * 1024)
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
APP_ENV = os.getenv("APP_ENV", "development").lower()
APP_ACCESS_TOKEN = os.getenv("APP_ACCESS_TOKEN", "")
RATE_LIMIT_MAX_REQUESTS = max(1, int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "60")))
RATE_LIMIT_WINDOW_SECONDS = max(1, int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")))
_rate_lock = threading.Lock()
_rate_hits = {}

KEYS = {
    "openai": OPENAI_KEY,
    "gemini": GEMINI_KEY,
    "claude": ANTHROPIC_KEY,
    "deepseek": DEEPSEEK_KEY,
}
KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

# --------------------------------------------------------------------------
# Specialist agents
# --------------------------------------------------------------------------

AGENTS = {
    "general": {
        "preferred": "auto",
        "system": "You are a helpful general assistant. Be concise and practical.",
    },
    "coding": {
        "preferred": "auto",
        "system": "You are a senior software engineer. Give correct, runnable code, "
        "explain trade-offs briefly, and flag security issues.",
    },
    "research": {
        "preferred": "gemini",
        "system": "You are a research assistant. Structure answers with sources of "
        "uncertainty noted, and cite what you are unsure about.",
    },
    "security": {
        "preferred": "auto",
        "system": "You are a cybersecurity and DevOps specialist. Focus on "
        "automation, hardening, detection, and safe defaults. Refuse harmful use.",
    },
}

# --------------------------------------------------------------------------
# Conversation memory (local JSON, no account needed)
# --------------------------------------------------------------------------


class ConversationMemory:
    def __init__(self, path=MEMORY_FILE, max_turns=MEMORY_MAX_TURNS):
        self.path = Path(path)
        self.max_turns = max_turns
        self.sessions = {}

    def load(self):
        try:
            self.sessions = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            self.sessions = {}
        return self

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.sessions, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def history(self, session_id):
        return list(self.sessions.get(session_id, []))

    def add(self, session_id, role, text):
        turns = self.sessions.setdefault(session_id, [])
        turns.append({"role": role, "text": text, "ts": datetime.now(timezone.utc).isoformat()})
        self.sessions[session_id] = turns[-self.max_turns * 2:]
        self.save()

    def clear(self, session_id):
        self.sessions.pop(session_id, None)
        self.save()


memory = ConversationMemory().load()

# --------------------------------------------------------------------------
# Provider routing (original OpenAI routing preserved)
# --------------------------------------------------------------------------


def choose_model(task: str) -> str:
    """Original OpenAI fast/strong routing baseline."""
    keywords = ("debug", "architecture", "analyze", "complex", "reason")
    return STRONG_MODEL if any(k in task.lower() for k in keywords) else FAST_MODEL


def available_providers():
    return [name for name, key in KEYS.items() if key]


def choose_provider(task: str, agent: str = "general") -> str:
    """Pick a provider. Safe default: OpenAI, or first configured provider."""
    if PROVIDER_OVERRIDE in KEYS:
        return PROVIDER_OVERRIDE
    preferred = AGENTS.get(agent, AGENTS["general"])["preferred"]
    if preferred in KEYS and KEYS[preferred]:
        return preferred
    coding_words = ("code", "debug", "function", "script", "python", "bug")
    if any(w in task.lower() for w in coding_words):
        for name in ("deepseek", "claude", "openai", "gemini"):
            if KEYS[name]:
                return name
    for name in ("openai", "gemini", "claude", "deepseek"):
        if KEYS[name]:
            return name
    return "openai"  # no key set; call layer explains what is missing


DISPLAY_NAMES = {"openai": "OpenAI", "gemini": "Gemini", "claude": "Claude", "deepseek": "DeepSeek"}



VISION_PROVIDERS = ("openai", "gemini", "claude")  # DeepSeek chat API has no image input
IMAGE_MIME_BY_EXT = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".webp": "image/webp",
}
IMAGE_MIMES = set(IMAGE_MIME_BY_EXT.values())
TEXT_EXTS = {".txt", ".md", ".py", ".json", ".csv", ".html", ".htm", ".js", ".ts",
             ".sh", ".yml", ".yaml", ".log", ".xml", ".css", ".java", ".c", ".cpp",
             ".go", ".rs", ".sql", ".ini", ".toml"}
DOC_EXTS = {".pdf", ".docx", ".zip"}
SUPPORTED_EXTS = set(IMAGE_MIME_BY_EXT) | TEXT_EXTS | DOC_EXTS

def upload_limits():
    return {"per_file_bytes": UPLOAD_MAX_BYTES, "max_files": MAX_UPLOAD_FILES,
            "total_bytes": UPLOAD_TOTAL_MAX_BYTES, "max_request_bytes": MAX_REQUEST_BYTES}

def capabilities():
    return {
        "providers": {k: {"configured": bool(v), "env_var": KEY_ENV[k],
                          "vision": k in VISION_PROVIDERS} for k, v in KEYS.items()},
        "agents": list(AGENTS),
        "images": {"extensions": sorted(IMAGE_MIME_BY_EXT), "mimes": sorted(IMAGE_MIMES),
                   "vision_providers": list(VISION_PROVIDERS),
                   "note": "Images are sent as vision input to OpenAI/Gemini/Claude. DeepSeek cannot see images; with auto routing the server picks a configured vision provider. With no vision provider configured it explains this instead of faking analysis."},
        "documents": {"extensions": sorted(SUPPORTED_EXTS),
                      "text_extracted": sorted(TEXT_EXTS | DOC_EXTS),
                      "note": "PDF/DOCX text is extracted locally (stdlib-only, best-effort). Scanned/image PDFs and binary files with no extractable text are reported, not guessed."},
        "limits": upload_limits(),
        "workspace": {"dir": WORKSPACE_DIR, "endpoints": ["/workspace/save", "/workspace/list", "/workspace/download", "/workspace/edit"],
                      "note": "Files are saved per session_id (use project/<name> for a persistent project). Paths are clamped to the workspace; traversal is rejected."},
        "projects": {"note": "Use session_id of the form project/<name> for a persistent project conversation. GET /memory/sessions lists all sessions with turn counts."},
        "limits_note": "Per-file/count/total limits are configurable via UPLOAD_MAX_BYTES, MAX_UPLOAD_FILES, UPLOAD_TOTAL_MAX_BYTES. Provider/API limits (model context, image size rules) and server safety limits cannot be removed by this app; raise the env vars if your providers allow larger files.",
    }

def missing_key_message(provider: str) -> str:
    return (
        f"{DISPLAY_NAMES.get(provider, provider)} is not configured: set {KEY_ENV[provider]} in your "
        f"environment to enable it. No request was sent. See README.md."
    )


def _http_json(url, headers, payload, timeout=60):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _openai_input(messages):
    out = []
    for m in messages:
        if m.get("attachments"):
            parts = [{"type": "input_text", "text": m.get("content", "")}]
            for a in m["attachments"]:
                if a.get("mime") in IMAGE_MIMES and a.get("data_b64"):
                    parts.append({"type": "input_image",
                                  "image_url": f"data:{a['mime']};base64,{a['data_b64']}"})
                elif a.get("kind") == "text" and a.get("text"):
                    parts.append({"type": "input_text",
                                  "text": f"[attachment {a.get('name')}]\n{a['text']}"})
            out.append({"role": m["role"], "content": parts})
        else:
            out.append({"role": m["role"], "content": m.get("content", "")})
    return out


def _call_openai(messages, task):
    if not OPENAI_KEY:
        return missing_key_message("openai")
    try:
        from openai import OpenAI

        client = OpenAI(api_key=OPENAI_KEY)
        response = client.responses.create(model=choose_model(task), input=_openai_input(messages))
        return response.output_text
    except Exception as exc:  # keep CLI/server alive, surface the cause
        return f"OpenAI error: {exc}"


def _call_gemini(messages, task):
    if not GEMINI_KEY:
        return missing_key_message("gemini")
    try:
        contents = []
        for m in messages:
            parts = [{"text": m.get("content", "")}]
            for a in m.get("attachments", []):
                if a.get("mime") in IMAGE_MIMES and a.get("data_b64"):
                    parts.append({"inline_data": {"mime_type": a["mime"], "data": a["data_b64"]}})
                elif a.get("kind") == "text" and a.get("text"):
                    parts.append({"text": f"[attachment {a.get('name')}]\n{a['text']}"})
            contents.append({"role": "user" if m["role"] == "user" else "model", "parts": parts})
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{MODEL_GEMINI}:generateContent?key={GEMINI_KEY}"
        )
        data = _http_json(url, {}, {"contents": contents})
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as exc:
        return f"Gemini error: {exc}"


def _call_claude(messages, task):
    if not ANTHROPIC_KEY:
        return missing_key_message("claude")
    try:
        system = AGENTS.get(agent_for(task), AGENTS["general"])["system"]
        payload_messages = []
        for m in messages:
            if m["role"] not in ("user", "assistant"):
                continue
            blocks = [{"type": "text", "text": m.get("content", "")}]
            for a in m.get("attachments", []):
                if a.get("mime") in IMAGE_MIMES and a.get("data_b64"):
                    blocks.append({"type": "image", "source": {"type": "base64",
                                     "media_type": a["mime"], "data": a["data_b64"]}})
                elif a.get("kind") == "text" and a.get("text"):
                    blocks.append({"type": "text",
                                   "text": f"[attachment {a.get('name')}]\n{a['text']}"})
            payload_messages.append({"role": m["role"], "content": blocks})
        data = _http_json(
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01"},
            {
                "model": MODEL_CLAUDE,
                "max_tokens": 1024,
                "system": system,
                "messages": payload_messages,
            },
        )
        return "".join(block.get("text", "") for block in data.get("content", []))
    except Exception as exc:
        return f"Claude error: {exc}"


def _call_deepseek(messages, task):
    if not DEEPSEEK_KEY:
        return missing_key_message("deepseek")
    if any(a.get("mime") in IMAGE_MIMES for m in messages for a in m.get("attachments", [])):
        return ("DeepSeek cannot analyze images: its chat API has no image input. "
                "Use provider openai, gemini, or claude (or auto, which picks a configured vision provider).")
    folded = []
    for m in messages:
        text = m.get("content", "")
        for a in m.get("attachments", []):
            if a.get("kind") == "text" and a.get("text"):
                text += f"\n[attachment {a.get('name')}]\n{a['text']}"
        folded.append({"role": m["role"], "content": text})
    try:
        data = _http_json(
            "https://api.deepseek.com/chat/completions",
            {"Authorization": f"Bearer {DEEPSEEK_KEY}"},
            {"model": MODEL_DEEPSEEK, "messages": folded},
        )
        return data["choices"][0]["message"]["content"]
    except Exception as exc:
        return f"DeepSeek error: {exc}"


PROVIDERS = {
    "openai": _call_openai,
    "gemini": _call_gemini,
    "claude": _call_claude,
    "deepseek": _call_deepseek,
}


def agent_for(task: str) -> str:
    low = task.lower()
    if any(w in low for w in ("code", "debug", "function", "script", "python", "bug", "compile")):
        return "coding"
    if any(w in low for w in ("research", "compare", "summarize", "explain", "what is")):
        return "research"
    if any(w in low for w in ("security", "vulnerability", "exploit", "harden", "devops", "auth")):
        return "security"
    return "general"


def choose_vision_provider(task, agent):
    if PROVIDER_OVERRIDE in VISION_PROVIDERS and KEYS[PROVIDER_OVERRIDE]:
        return PROVIDER_OVERRIDE
    for name in ("openai", "gemini", "claude"):
        if KEYS[name]:
            return name
    return None


def answer(task: str, agent=None, provider=None, session_id="cli", attachments=None) -> str:
    """Ask the orchestrator and record the turn in memory."""
    agent = agent or agent_for(task)
    has_images = bool(attachments) and any(a.get("mime") in IMAGE_MIMES for a in attachments)
    if provider in (None, "", "auto"):
        if has_images:
            vp = choose_vision_provider(task, agent)
            if vp is None:
                return ("No vision-capable provider is configured for image analysis. Set one of "
                        "OPENAI_API_KEY, GEMINI_API_KEY, ANTHROPIC_API_KEY and retry. "
                        "DeepSeek cannot see images. See README.md capability matrix.")
            provider = vp
        else:
            provider = choose_provider(task, agent)
    if provider not in PROVIDERS:
        return f"Unknown provider '{provider}'. Choose openai, gemini, claude, or deepseek."
    history = memory.history(session_id)
    system = AGENTS.get(agent, AGENTS["general"])["system"]
    messages = [{"role": "system", "content": system}]
    messages += [{"role": h["role"], "content": h["text"]} for h in history]
    user_msg = {"role": "user", "content": task}
    if attachments:
        user_msg["attachments"] = attachments
    messages.append(user_msg)
    reply = PROVIDERS[provider](messages, task)
    if not reply.startswith(("OpenAI error", "Gemini error", "Claude error", "DeepSeek error")) and "is not configured" not in reply and "cannot analyze images" not in reply and "No vision-capable provider" not in reply:
        names = ", ".join(a.get("name", "file") for a in attachments) if attachments else None
        memory.add(session_id, "user", task + (f" [attachments: {names}]" if names else ""))
        memory.add(session_id, "assistant", reply)
    return reply


# --------------------------------------------------------------------------
# File processing: images (vision) + documents/text (extracted locally)
# --------------------------------------------------------------------------
# No API keys here. Uploads are validated (extension + magic bytes + size),
# never executed, and never written to disk by the server.

def _extract_pdf_text(raw: bytes) -> str:
    """Best-effort stdlib-only PDF text: FlateDecode streams, Tj/TJ strings."""
    texts = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S):
        blob = m.group(1)
        try:
            blob = zlib.decompress(blob)
        except Exception:
            pass
        for sm in re.finditer(rb"\((?:[^()\\]|\\.)*\)\s*Tj", blob):
            texts.append(sm.group(0))
        for tj in re.finditer(rb"\[((?:[^\[\]]|\([^()]*\))*)\]\s*TJ", blob):
            texts.append(tj.group(1))
    if not texts:
        raise ValueError("No extractable text found in this PDF (it may be scanned/image-based; this app does not do OCR).")
    out = []
    for chunk in texts:
        parts = re.findall(rb"\((.*)\)", chunk, re.S)
        for part in parts:
            t = part.replace(b"\\(", b"(").replace(b"\\)", b")").replace(b"\\\\", b"\\")
            try:
                out.append(t.decode("latin-1"))
            except Exception:
                pass
    text = " ".join(out)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise ValueError("No extractable text found in this PDF (it may be scanned/image-based; this app does not do OCR).")
    return text


def _extract_docx_text(raw: bytes) -> str:
    """Best-effort stdlib-only DOCX text from word/document.xml."""
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            xml_bytes = zf.read("word/document.xml")
    except Exception:
        raise ValueError("This file is not a valid .docx (zip/word/document.xml missing).")
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        text = re.sub(r"<[^>]+>", " ", xml_bytes.decode("utf-8", "replace"))
        text = _html.unescape(re.sub(r"\s+", " ", text).strip())
        if not text:
            raise ValueError("No extractable text found in this document.")
        return text
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paras = []
    for para in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
        paras.append("".join(t.text or "" for t in para.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")))
    text = "\n".join(paras).strip()
    if not text:
        raise ValueError("No extractable text found in this document.")
    return text



ZIP_MAX_MEMBERS_DEFAULT = 200


def _extract_zip_text(raw: bytes) -> str:
    """List members and extract text from safe text/doc members of a zip.
    Protects against zip bombs and path traversal (never writes to disk)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except Exception:
        raise ValueError("This file is not a valid .zip archive.")
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > MAX_ZIP_MEMBERS:
        raise ValueError(f"Archive has too many files ({len(infos)}); limit is {MAX_ZIP_MEMBERS}.")
    if sum(i.file_size for i in infos) > MAX_ZIP_UNCOMPRESSED_BYTES:
        raise ValueError("Uncompressed archive size exceeds the server limit.")
    parts = [f"Archive contents ({len(infos)} file(s)):"]
    total = 0
    for info in infos:
        name = info.filename
        if ".." in name.replace("\\", "/").split("/") or name.startswith(("/", "\\")):
            parts.append(f"- {name} [skipped: unsafe path]")
            continue
        ext = Path(name).suffix.lower()
        parts.append(f"- {name} ({info.file_size} bytes)")
        if ext in TEXT_EXTS:
            try:
                data = zf.read(info)
            except Exception:
                continue
            total += len(data)
            text = _decode_text(data)
            if len(text.encode("utf-8")) > MAX_FILE_BYTES:
                text = text[:MAX_FILE_BYTES] + f"\n[truncated at {MAX_FILE_BYTES} bytes]"
            parts.append(text)
            if total > UPLOAD_TOTAL_MAX_BYTES:
                parts.append("[stopped extracting: too much text]")
                break
        elif ext in (".pdf", ".docx"):
            try:
                data = zf.read(info)
                text = _extract_pdf_text(data) if ext == ".pdf" else _extract_docx_text(data)
                parts.append(text)
            except Exception as exc:
                parts.append(f"[{name}: {exc}]")
    return "\n".join(parts)


def _sniff_ok(ext: str, raw: bytes) -> bool:
    head = raw[:16]
    if ext in (".jpg", ".jpeg"):
        return raw[:3] == b"\xff\xd8\xff"
    if ext == ".png":
        return raw[:8] == b"\x89PNG\r\n\x1a\n"
    if ext == ".gif":
        return raw[:6] in (b"GIF87a", b"GIF89a")
    if ext == ".webp":
        return raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
    if ext == ".pdf":
        return raw[:4] == b"%PDF"
    if ext in (".docx", ".zip"):
        return raw[:2] == b"PK"
    return True  # text types: decoded with replacement below, no magic check


def _decode_text(raw: bytes) -> str:
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def validate_attachment(filename, raw: bytes, mime=None):
    """Validate one uploaded file. Returns normalized attachment dict.
    Raises ValueError with a user-facing reason."""
    name = Path(str(filename or "file")).name
    ext = Path(name).suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise ValueError(f"Unsupported file type '{ext or name}'. Supported: {sorted(SUPPORTED_EXTS)}")
    if len(raw) > UPLOAD_MAX_BYTES:
        raise ValueError(f"'{name}' is {len(raw)} bytes, over the {UPLOAD_MAX_BYTES}-byte per-file limit. "
                         "Raise UPLOAD_MAX_BYTES on the server if your provider allows it.")
    if not _sniff_ok(ext, raw):
        raise ValueError(f"'{name}' does not look like a real {ext} file (magic bytes mismatch).")
    if ext in IMAGE_MIME_BY_EXT:
        return {"name": name, "ext": ext, "mime": IMAGE_MIME_BY_EXT[ext], "kind": "image",
                "size": len(raw), "data_b64": base64.b64encode(raw).decode("ascii")}
    if ext == ".pdf":
        text = _extract_pdf_text(raw)
    elif ext == ".docx":
        text = _extract_docx_text(raw)
    elif ext == ".zip":
        text = _extract_zip_text(raw)
    else:
        text = _decode_text(raw)
    if len(text.encode("utf-8")) > MAX_FILE_BYTES:
        text = text[:MAX_FILE_BYTES] + f"\n[truncated at {MAX_FILE_BYTES} bytes]"
    return {"name": name, "ext": ext, "mime": "text/plain", "kind": "text",
            "size": len(raw), "text": text}


def normalize_uploads(data):
    """Build attachments list from /upload/* payloads. Enforces count/total limits."""
    files = data.get("files") or []
    if not files:
        raise ValueError("No files provided.")
    if len(files) > MAX_UPLOAD_FILES:
        raise ValueError(f"Too many files ({len(files)}). Limit is {MAX_UPLOAD_FILES} per request; "
                         "raise MAX_UPLOAD_FILES on the server if needed.")
    total = sum(len(f.get("data_b64", "")) * 3 // 4 for f in files)
    if total > UPLOAD_TOTAL_MAX_BYTES:
        raise ValueError(f"Total upload size is too large (limit {UPLOAD_TOTAL_MAX_BYTES} bytes). "
                         "Raise UPLOAD_TOTAL_MAX_BYTES on the server if needed.")
    attachments = []
    for f in files:
        raw_b64 = f.get("data_b64") or ""
        try:
            raw = base64.b64decode(raw_b64, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError(f"File '{f.get('filename')}' is not valid base64 data.")
        attachments.append(validate_attachment(f.get("filename"), raw))
    return attachments


TEXT_SUFFIXES = SUPPORTED_EXTS  # kept name for CLI /analyze compatibility


def read_file_text(path_str, filename=None, content=None):
    """Legacy helper (CLI /analyze). Now routes through validate_attachment."""
    if content is not None:
        raw = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        att = validate_attachment(filename or path_str or "uploaded file", raw)
        if att["kind"] != "text":
            raise ValueError(f"'{att['name']}' is an image; use /upload/analyze or /chat with an image instead.")
        return att["name"], att["text"]
    path = Path(path_str or "").expanduser()
    if not path.is_file():
        raise ValueError(f"File not found: {path_str}")
    raw = path.read_bytes()
    att = validate_attachment(path.name, raw)
    if att["kind"] != "text":
        raise ValueError(f"'{att['name']}' is an image; use /upload/analyze or /chat with an image instead.")
    return att["name"], att["text"]


def analyze_file(task, filename=None, path=None, content=None, **kw):
    name, text = read_file_text(path, filename=filename, content=content)
    prompt = f"Analyze this file ({name}). Question: {task}\n\n--- file start ---\n{text}\n--- file end ---"
    return answer(prompt, **kw)


def analyze_attachments(task, data, **kw):
    attachments = normalize_uploads(data)
    names = ", ".join(a["name"] for a in attachments)
    prompt = (f"The user uploaded {len(attachments)} file(s): {names}. "
              f"Question: {task or 'Analyze these files.'}")
    return answer(prompt, attachments=attachments, **kw)



# --------------------------------------------------------------------------
# Workspace: generated files saved per session, downloadable, path-safe
# --------------------------------------------------------------------------

def _safe_join(root, *parts):
    base = Path(root).resolve()
    target = base.joinpath(*[str(x) for x in parts]).resolve()
    if base not in target.parents and target != base:
        raise ValueError("Unsafe path.")
    return target


def workspace_root(session_id="web"):
    sid = re.sub(r"[^A-Za-z0-9._-]+", "_", str(session_id or "web")).strip("._") or "web"
    root = _safe_join(Path(WORKSPACE_DIR), sid)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_filename(filename):
    name = Path(str(filename or "")).name
    name = name.strip()
    if not name or name in (".", "..") or "/" in name or "\\" in name or "\x00" in name:
        raise ValueError("Invalid filename.")
    return name


def workspace_save(session_id, filename, content):
    name = _safe_filename(filename)
    if not isinstance(content, str):
        raise ValueError("content must be text.")
    if len(content.encode("utf-8")) > UPLOAD_MAX_BYTES:
        raise ValueError("File content exceeds the server upload limit.")
    path = _safe_join(workspace_root(session_id), name)
    path.write_text(content, encoding="utf-8")
    return {"file": name, "size": path.stat().st_size,
            "download": f"/workspace/download?session_id={session_id}&file={name}"}


def workspace_list(session_id):
    root = workspace_root(session_id)
    return [{"file": f.name, "size": f.stat().st_size,
             "download": f"/workspace/download?session_id={session_id}&file={f.name}"}
            for f in sorted(root.iterdir()) if f.is_file()]


def workspace_read(session_id, filename):
    return _safe_join(workspace_root(session_id), _safe_filename(filename)).read_bytes()


def workspace_edit(session_id, filename, old_text, new_text):
    path = _safe_join(workspace_root(session_id), _safe_filename(filename))
    if not path.is_file():
        raise ValueError(f"File not found: {filename}")
    text = path.read_text(encoding="utf-8")
    if old_text not in text:
        raise ValueError("old_text not found in the file.")
    path.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")
    return {"file": path.name, "status": "edited"}


def memory_sessions():
    return [{"session_id": sid, "turns": len(turns) // 2}
            for sid, turns in sorted(memory.sessions.items())]


# --------------------------------------------------------------------------
# API / backend server + Android-compatible web UI (stdlib only)
# --------------------------------------------------------------------------

INDEX_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Integrated AI</title>
<style>
body{font-family:system-ui,sans-serif;margin:0 auto;max-width:720px;padding:12px}
#log{border:1px solid #ccc;border-radius:8px;padding:8px;min-height:200px;white-space:pre-wrap}
textarea,input,select{width:100%%;box-sizing:border-box;margin:6px 0;padding:8px;font-size:16px}
button{padding:10px 16px;font-size:16px}
.msg{margin:8px 0}.user{font-weight:700}
</style></head><body>
<h1>Integrated AI</h1>
<div id="log">Ask a question, or attach images and documents.</div>
<select id="agent"><option>general</option><option>coding</option><option>research</option><option>security</option><option>assignment</option></select>
<select id="provider"><option>auto</option><option>openai</option><option>gemini</option><option>claude</option><option>deepseek</option></select>
<textarea id="q" rows="3" placeholder="Type a message"></textarea>
<input type="file" id="f" multiple accept=".jpg,.jpeg,.png,.gif,.webp,.pdf,.docx,.txt,.md,.py,.json,.csv,.html,.js,.sh,.yml,.yaml,.log">
<button onclick="send()">Send (with attachments if selected)</button>
<script>
function b64(buf){let b='';const bytes=new Uint8Array(buf);for(let i=0;i<bytes.length;i+=0x8000){b+=String.fromCharCode.apply(null,bytes.subarray(i,i+0x8000));}return btoa(b);}
async function send(){
 const files=[...document.getElementById('f').files];
 const payload={message:document.getElementById('q').value,agent:document.getElementById('agent').value,provider:document.getElementById('provider').value};
 if(files.length){
   payload.files=[];
   for(const f of files){const buf=await f.arrayBuffer();payload.files.push({filename:f.name,data_b64:b64(buf)});}
 }
 const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
 const d=await r.json(); log('You: '+payload.message+'\\nAI: '+(d.reply||d.error));
}
function log(t){const e=document.getElementById('log');e.textContent=t+'\\n---\\n'+e.textContent;}
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _guard_request(self):
        now = time.monotonic()
        client_ip = self.client_address[0] if self.client_address else "unknown"
        with _rate_lock:
            hits = [stamp for stamp in _rate_hits.get(client_ip, []) if now - stamp < RATE_LIMIT_WINDOW_SECONDS]
            if len(hits) >= RATE_LIMIT_MAX_REQUESTS:
                self._json(429, {"error": "Too many requests. Please wait and try again."})
                return False
            hits.append(now)
            _rate_hits[client_ip] = hits
        path = self.path.split("?", 1)[0]
        if path in ("/", "/health"):
            return True
        if APP_ENV == "production" and not APP_ACCESS_TOKEN:
            self._json(503, {"error": "Server access token is not configured."})
            return False
        if APP_ACCESS_TOKEN or APP_ENV == "production":
            supplied = self.headers.get("Authorization", "")
            expected = "Bearer " + APP_ACCESS_TOKEN
            if not APP_ACCESS_TOKEN or not hmac.compare_digest(supplied, expected):
                self._json(401, {"error": "Unauthorized. Add your backend access token."})
                return False
        return True

    def _json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > MAX_REQUEST_BYTES:
            raise ValueError(f"Request body too large (limit {MAX_REQUEST_BYTES} bytes).")
        raw = self.rfile.read(length) if length else b"{}"
        if self.headers.get("Content-Type", "").startswith("application/json"):
            return json.loads(raw.decode("utf-8") or "{}")
        return {}

    def _query(self):
        from urllib.parse import urlparse, parse_qs
        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

    def do_GET(self):
        if not self._guard_request():
            return
        if self.path == "/":
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/health":
            self._json(200, {"status": "ok", "providers": {k: bool(v) for k, v in KEYS.items()}, "uploads": upload_limits()})
        elif self.path == "/providers":
            self._json(200, capabilities())
        elif self.path.startswith("/workspace/list"):
            qs = self._query()
            self._json(200, {"files": workspace_list(qs.get("session_id", "web"))})
        elif self.path.startswith("/workspace/download"):
            qs = self._query()
            try:
                data = workspace_read(qs.get("session_id", "web"), qs.get("file", ""))
            except (ValueError, FileNotFoundError) as exc:
                return self._json(404, {"error": str(exc)})
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f"attachment; filename=\"{Path(qs.get('file', 'file')).name}\"")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif self.path == "/memory/sessions":
            self._json(200, {"sessions": memory_sessions()})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if not self._guard_request():
            return
        try:
            data = self._body()
            if self.path == "/chat":
                task = str(data.get("message", "")).strip()
                attachments = normalize_uploads(data) if data.get("files") else None
                if not task and not attachments:
                    return self._json(400, {"error": "message or files is required"})
                if not task:
                    task = "Analyze the attached file(s)."
                reply = answer(
                    task,
                    agent=data.get("agent"),
                    provider=data.get("provider"),
                    session_id=str(data.get("session_id", "web")),
                    attachments=attachments,
                )
                self._json(200, {"reply": reply})
            elif self.path == "/upload/analyze":
                task = str(data.get("question", "Analyze these files."))
                reply = analyze_attachments(
                    task, data,
                    agent=data.get("agent"),
                    provider=data.get("provider"),
                    session_id=str(data.get("session_id", "web")),
                )
                self._json(200, {"reply": reply})
            elif self.path == "/process-file":
                if data.get("files"):
                    reply = analyze_attachments(
                        str(data.get("question", "Analyze these files.")), data,
                        agent=data.get("agent"), provider=data.get("provider"),
                        session_id=str(data.get("session_id", "web")),
                    )
                    return self._json(200, {"reply": reply})
                content = data.get("content")
                if content is None and data.get("content_base64"):
                    try:
                        raw = base64.b64decode(data["content_base64"], validate=True)
                    except (binascii.Error, ValueError):
                        return self._json(400, {"error": "content_base64 is not valid base64."})
                    att = validate_attachment(data.get("filename"), raw)
                    if att["kind"] == "image":
                        content = None
                        reply = analyze_attachments(
                            str(data.get("question", "Analyze this image.")), {"files": [data]},
                            agent=data.get("agent"), provider=data.get("provider"),
                            session_id=str(data.get("session_id", "web")),
                        )
                        return self._json(200, {"reply": reply})
                    content = att["text"]
                reply = analyze_file(
                    str(data.get("question", "Summarize this file")),
                    filename=data.get("filename"),
                    content=content,
                    agent=data.get("agent"),
                    provider=data.get("provider"),
                    session_id=str(data.get("session_id", "web")),
                )
                self._json(200, {"reply": reply})
            elif self.path == "/workspace/save":
                info = workspace_save(str(data.get("session_id", "web")), data.get("filename"), data.get("content", ""))
                self._json(200, info)
            elif self.path == "/workspace/edit":
                info = workspace_edit(str(data.get("session_id", "web")), data.get("filename"),
                                      str(data.get("old_text", "")), str(data.get("new_text", "")))
                self._json(200, info)
            elif self.path == "/clear":
                memory.clear(str(data.get("session_id", "web")))
                self._json(200, {"status": "cleared"})
            else:
                self._json(404, {"error": "not found"})
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:
            self._json(500, {"error": str(exc)})


def serve():
    if APP_ENV == "production" and not APP_ACCESS_TOKEN:
        raise SystemExit("Refusing to start in production without APP_ACCESS_TOKEN.")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Integrated AI serving on http://{HOST}:{PORT} (open in an Android browser on the same network)")
    print(f"Configured providers: {available_providers() or 'none (set an API key env var, see README.md)'}")
    print(f"Uploads: max {MAX_UPLOAD_FILES} files, {UPLOAD_MAX_BYTES} bytes/file, {UPLOAD_TOTAL_MAX_BYTES} bytes total")
    print(f"Workspace: {WORKSPACE_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def cli():
    agent = AGENT_OVERRIDE
    provider = PROVIDER_OVERRIDE
    print(f"Integrated AI CLI. Agent: {agent}. Provider: {provider}.")
    print(f"Configured providers: {available_providers() or 'none yet (set an API key env var)'}")
    print("Commands: /agent <name>, /provider <name>, /analyze <path>, /memory, /clear, quit")
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if line.lower() in {"quit", "exit"}:
            break
        if not line:
            continue
        if line.startswith("/agent "):
            name = line.split()[1].lower()
            if name in AGENTS:
                agent = name
                print(f"agent set to {name}")
            else:
                print(f"unknown agent. choose from {list(AGENTS)}")
            continue
        if line.startswith("/provider "):
            name = line.split()[1].lower()
            if name in PROVIDERS or name == "auto":
                provider = name
                print(f"provider set to {name}")
            else:
                print(f"unknown provider. choose from {list(PROVIDERS)} or auto")
            continue
        if line.startswith("/analyze "):
            path = line[len("/analyze "):].strip()
            try:
                result = analyze_file(
                    "Summarize this file and note anything important",
                    path=path, agent=agent,
                    provider=None if provider == "auto" else provider,
                )
            except ValueError as exc:
                result = str(exc)
            print("ai>", result)
            continue
        if line == "/memory":
            print(f"memory turns stored: {len(memory.history('cli')) // 2}")
            continue
        if line == "/clear":
            memory.clear("cli")
            print("memory cleared")
            continue
        print("ai>", answer(line, agent=agent, provider=None if provider == "auto" else provider))


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        serve()
    else:
        cli()
