# Integrated AI — Android app

Native Android client (Kotlin, Android Views) for the Python backend in the parent folder (`../main.py`). The backend is unchanged and still runs with `python main.py serve` (default port 8000).

## What this app does

- Chat screen backed by `POST /chat` (`message`, `agent`, `provider`, `session_id`)
- Provider + agent pickers matching the backend (`auto`, `openai`, `gemini`, `claude`, `deepseek` and `general`, `coding`, `research`, `security`)
- Connection check using `GET /health` and `GET /providers`
- Clear button using `POST /clear`
- Attach file button (multi-select: images jpg/png/gif/webp, pdf, docx, text/code files) with an attached-files label
- Analyze files button using `POST /upload/analyze` (question from the message box); images are analyzed by a vision-capable backend provider (OpenAI/Gemini/Claude), documents are text-extracted server-side. DeepSeek cannot see images.
- Chat with attachments also works through `POST /chat` (`files: [{filename, data_b64}]`)
- Configurable backend URL stored in SharedPreferences (no API keys in the app)

No AI provider keys live in this Android app. Uploaded files are base64-encoded and sent only to the configured backend URL, never to a provider directly.

Upload limits are enforced on the backend (`UPLOAD_MAX_BYTES` = 50 MB/file, `MAX_UPLOAD_FILES` = 10, `UPLOAD_TOTAL_MAX_BYTES` = 200 MB by default, configurable via env vars, no arbitrary low cap). The app has no hard client cap; the backend enforces these. Provider/model limits still apply on top of these; see the parent README's limits section. Check `/health` or `/providers` for the active limits and the vision capability matrix. Keys stay server-side in environment variables (`OPENAI_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`) — see `../README.md`.

## Setup and build

Prerequisites:

- JDK 17
- Android Studio Hedgehog or newer (bundles JDK 17), or Android Studio Ladybug
- Android SDK installed via Studio SDK Manager (API 34)

Build from the command line:

```bash
cd android-app
# First time only: generate the Gradle wrapper (needs Java 17)
gradle wrapper --gradle-version 8.7
./gradlew assembleDebug
# Or open this folder in Android Studio and run the app on a device/emulator
```

Debug APK lands at `app/build/outputs/apk/debug/app-debug.apk`.

## Run the backend first

```bash
cd ..
pip install -r requirements.txt
export OPENAI_API_KEY="***"   # and/or other provider keys
python main.py serve
```

Do not expose the Python server to the public internet: it has no authentication. Use it on your own LAN or behind a password-protected tunnel.

## Emulator localhost note (important)

Inside the Android emulator, `127.0.0.1` / `localhost` is the emulator itself, not your computer. Use `10.0.2.2` to reach the host machine:

- Default URL in the app: `http://10.0.2.2:8000`
- On a physical phone: use your computer's LAN IP, e.g. `http://192.168.1.100:8000`, in the backend URL field, then tap Save.

The app has a Check button that calls `/health` and `/providers` and shows what happened.

## Cleartext policy (local dev only)

`app/src/main/res/xml/network_security_config.xml` allows plain HTTP cleartext only for `10.0.2.2`, `localhost`, `127.0.0.1`, and a few sample `192.168.x.x` LAN IPs. Everything else requires HTTPS (`base-config cleartextTrafficPermitted="false"`). For any public backend, serve it over HTTPS and use an `https://` URL. Do not widen this config in a production build.

## Package and versions

- Package: `com.integratedai.app`
- Min SDK 26, Target/Compile SDK 34, version 1.0 (code 1)
- Kotlin 1.9.24, Android Gradle Plugin 8.5.2, Gradle 8.7, Java 17
- Dependencies: AppCompat 1.7.0, Material 1.12.0, RecyclerView 1.3.2, Kotlin coroutines 1.7.3

## Status

Scaffold built from source. No APK was built in the environment where this was authored (no JDK/Android SDK available there). Open it in Android Studio and let it sync, then install on a device or emulator.
