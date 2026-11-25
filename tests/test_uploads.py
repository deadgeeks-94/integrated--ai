"""Smoke tests for integrated-ai upload/workspace features.
Run: python3 tests/test_uploads.py
No API keys needed; provider calls are exercised only for the no-key paths."""
import base64, io, json, os, sys, tempfile, threading, urllib.request, urllib.error, zipfile

os.environ["MEMORY_FILE"] = tempfile.mktemp(suffix=".json")
os.environ["WORKSPACE_DIR"] = tempfile.mkdtemp(prefix="ws_")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import main  # noqa: E402

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


def expect_value_error(fn, label):
    try:
        fn()
    except ValueError:
        print(f"PASS {label}")
        return
    raise SystemExit(f"FAIL {label}: expected ValueError")


def test_gemini_only_configuration():
    caps = main.capabilities()
    assert caps["provider"] == "gemini"
    assert list(caps["providers"].keys()) == ["gemini"]
    assert {"coding", "research", "study", "arabic", "math"}.issubset(set(caps["agents"]))
    print("PASS Gemini-only provider and specialist modes")


def test_validation():
    att = main.validate_attachment("photo.png", PNG)
    assert att["mime"] == "image/png" and att["kind"] == "image"
    print("PASS png accepted")
    expect_value_error(lambda: main.validate_attachment("fake.png", b"not a png"), "fake png rejected")
    expect_value_error(lambda: main.validate_attachment("evil.exe", b"MZ"), "exe rejected")
    txt = main.validate_attachment("a.py", b"print(1)")
    assert txt["kind"] == "text" and "print" in txt["text"]
    print("PASS code text accepted")


def test_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("notes.txt", "from zip")
        zf.writestr("../evil.txt", "skip me")
    att = main.validate_attachment("p.zip", buf.getvalue())
    assert "skip me" not in att["text"] and "unsafe path" in att["text"]
    print("PASS zip extraction + traversal skipped")


def test_no_key_paths():
    img = main.validate_attachment("p.png", PNG)
    r = main.answer("Describe this", attachments=[img])
    assert "vision" in r.lower() or "not configured" in r
    print("PASS image no-key message")


def test_http():
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", 0), main.Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def post(path, payload):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                     data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    st, info = post("/workspace/save", {"session_id": "project/t", "filename": "a.txt", "content": "hello"})
    assert st == 200 and info["file"] == "a.txt"
    print("PASS workspace save")
    st, _ = post("/workspace/edit", {"session_id": "project/t", "filename": "a.txt",
                                     "old_text": "hello", "new_text": "world"})
    assert st == 200
    print("PASS workspace edit")
    st, r = post("/chat", {"message": "x", "files": [{"filename": "a.txt", "data_b64": "!!!"}]})
    assert st == 400
    print("PASS bad base64 400")
    srv.shutdown()


if __name__ == "__main__":
    test_gemini_only_configuration()
    test_validation()
    test_zip()
    test_no_key_paths()
    test_http()
    print("ALL TESTS PASSED")
