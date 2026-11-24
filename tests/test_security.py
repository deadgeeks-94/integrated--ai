"""Security guard tests; run with python tests/test_security.py."""
import os
import sys
from email.message import Message

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import main


class DummyHandler:
    _guard_request = main.Handler._guard_request

    def __init__(self, path="/providers", authorization=""):
        self.path = path
        self.headers = Message()
        if authorization:
            self.headers["Authorization"] = authorization
        self.client_address = ("127.0.0.77", 12345)
        self.responses = []

    def _json(self, code, body):
        self.responses.append((code, body))


def test_auth_required():
    old_env, old_token = main.APP_ENV, main.APP_ACCESS_TOKEN
    try:
        main.APP_ENV, main.APP_ACCESS_TOKEN = "development", "test-secret"
        h = DummyHandler()
        assert h._guard_request() is False
        assert h.responses[0][0] == 401
        h = DummyHandler(authorization="Bearer test-secret")
        assert h._guard_request() is True
        h = DummyHandler(path="/health")
        assert h._guard_request() is True
        print("PASS bearer auth and public health")
    finally:
        main.APP_ENV, main.APP_ACCESS_TOKEN = old_env, old_token


def test_production_fails_closed():
    old_env, old_token = main.APP_ENV, main.APP_ACCESS_TOKEN
    try:
        main.APP_ENV, main.APP_ACCESS_TOKEN = "production", ""
        h = DummyHandler()
        assert h._guard_request() is False
        assert h.responses[0][0] == 503
        print("PASS production requires configured token")
    finally:
        main.APP_ENV, main.APP_ACCESS_TOKEN = old_env, old_token


def test_rate_limit():
    old_max, old_window, old_env, old_token = (
        main.RATE_LIMIT_MAX_REQUESTS, main.RATE_LIMIT_WINDOW_SECONDS,
        main.APP_ENV, main.APP_ACCESS_TOKEN
    )
    try:
        main.RATE_LIMIT_MAX_REQUESTS = 1
        main.RATE_LIMIT_WINDOW_SECONDS = 60
        main.APP_ENV, main.APP_ACCESS_TOKEN = "development", "test-secret"
        with main._rate_lock:
            main._rate_hits.clear()
        h1 = DummyHandler(authorization="Bearer test-secret")
        assert h1._guard_request() is True
        h2 = DummyHandler(authorization="Bearer test-secret")
        assert h2._guard_request() is False
        assert h2.responses[0][0] == 429
        print("PASS per-IP rate limit")
    finally:
        main.RATE_LIMIT_MAX_REQUESTS = old_max
        main.RATE_LIMIT_WINDOW_SECONDS = old_window
        main.APP_ENV, main.APP_ACCESS_TOKEN = old_env, old_token
        with main._rate_lock:
            main._rate_hits.clear()


if __name__ == "__main__":
    test_auth_required()
    test_production_fails_closed()
    test_rate_limit()
    print("ALL SECURITY TESTS PASSED")
