# GitHub quick start

1. Create a **private** GitHub repository.
2. Extract this archive on your device/computer.
3. Upload the contents of the `integrated-ai` folder (not the outer folder itself) into the repository root.
4. Commit the files to `main`.
5. Open the repository's **Actions** tab.
6. Wait for **Backend tests** and **Android debug APK** to finish.
7. Download `integrated-ai-debug-apk` from the successful Android workflow run.

The backend tests can run without provider API keys. Live model responses require provider API keys configured on the backend. Do not put API keys in GitHub or inside the Android app.

The backend currently has no authentication. Do not expose it to the public internet.
