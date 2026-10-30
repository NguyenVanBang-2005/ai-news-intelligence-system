"""Security headers on every response, and /static serving only files of app/static."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.core.security_headers import SECURITY_HEADERS
from app.main import STATIC_DIR, app


@pytest.fixture
def web() -> TestClient:
    """A client without a database: these paths never touch one."""
    return TestClient(app)


def assert_security_headers(response) -> None:
    for name, value in SECURITY_HEADERS.items():
        assert response.headers.get(name) == value, name


# --- headers -----------------------------------------------------------------------------


def test_expected_header_values() -> None:
    assert SECURITY_HEADERS == {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    }


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("/", 200),
        ("/api/v1/health", 200),
        ("/api/v1/does-not-exist", 404),
        ("/static/index.html", 200),
        ("/static/missing.css", 404),
        ("/docs", 200),
        ("/redoc", 200),
        ("/openapi.json", 200),
    ],
)
def test_every_response_has_the_security_headers(web: TestClient, path: str, status: int) -> None:
    response = web.get(path)

    assert response.status_code == status
    assert_security_headers(response)


def test_body_limit_refusal_also_has_the_headers(web: TestClient) -> None:
    response = web.post("/api/v1/ai/search", content=b"x" * 10_000)

    assert response.status_code == 413
    assert_security_headers(response)


def test_api_responses_have_no_content_security_policy(web: TestClient) -> None:
    # The CSP is for the web UI only (see tests/test_web_ui.py).
    assert "Content-Security-Policy" not in web.get("/api/v1/health").headers


def test_docs_pages_still_load_swagger_and_redoc(web: TestClient) -> None:
    docs, redoc = web.get("/docs"), web.get("/redoc")

    assert "swagger-ui" in docs.text and "/openapi.json" in docs.text
    assert "redoc" in redoc.text.lower()


# --- static files ------------------------------------------------------------------------


def test_root_still_serves_the_search_page(web: TestClient) -> None:
    response = web.get("/")

    assert response.headers["content-type"].startswith("text/html")
    assert response.content == (STATIC_DIR / "index.html").read_bytes()


def test_existing_static_file_is_served_with_its_type(web: TestClient) -> None:
    response = web.get("/static/index.html")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.content == (STATIC_DIR / "index.html").read_bytes()


@pytest.mark.parametrize("path", ["/static/missing.js", "/static/", "/static"])
def test_missing_files_and_the_directory_itself_are_404(web: TestClient, path: str) -> None:
    assert web.get(path).status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/static/../main.py",
        "/static/%2e%2e/main.py",
        "/static/%2E%2E/main.py",
        "/static/..%2fmain.py",
        "/static/%2e%2e%2fmain.py",
        "/static/..%5cmain.py",
        "/static/%2e%2e/%2e%2e/README.md",
        "/static/%2e%2e/core/config.py",
    ],
)
def test_path_traversal_cannot_read_files_outside_static(web: TestClient, path: str) -> None:
    response = web.get(path)

    assert response.status_code == 404
    assert b"FastAPI" not in response.content
    assert b"import" not in response.content


RAW_CALL_TIMEOUT_SECONDS = 10


def make_receive():
    """An ASGI `receive`: an empty request body first, then an immediate disconnect.

    Answering http.request forever made a response that waits for http.disconnect spin
    without end (it hung CI). The disconnect is returned at once, without waiting.
    """
    calls = 0

    async def receive() -> dict:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    return receive


async def call_app_with_timeout(scope: dict, send) -> None:
    """Run the app once; fail clearly after RAW_CALL_TIMEOUT_SECONDS instead of hanging."""
    try:
        await asyncio.wait_for(app(scope, make_receive(), send), RAW_CALL_TIMEOUT_SECONDS)
    except TimeoutError:
        pytest.fail(f"app did not answer {scope['path']!r} within {RAW_CALL_TIMEOUT_SECONDS}s")


def send_raw_path(path: str) -> tuple[int, bytes]:
    """Call the app with `path` exactly as given; HTTP clients would remove "../" first."""
    messages: list[dict] = []
    scope = {
        "type": "http", "http_version": "1.1", "method": "GET", "scheme": "http",
        "path": path, "raw_path": path.encode(), "root_path": "", "query_string": b"",
        "headers": [(b"host", b"testserver")], "server": ("testserver", 80),
        "client": ("127.0.0.1", 1234),
    }

    async def send(message: dict) -> None:
        messages.append(message)

    asyncio.run(call_app_with_timeout(scope, send))
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return messages[0]["status"], body


def test_receive_disconnects_right_after_the_request() -> None:
    async def first_three_messages() -> list[dict]:
        receive = make_receive()
        return [await asyncio.wait_for(receive(), timeout=1) for _ in range(3)]

    first, second, third = asyncio.run(first_three_messages())

    assert first == {"type": "http.request", "body": b"", "more_body": False}
    assert second == third == {"type": "http.disconnect"}


def test_raw_path_helper_serves_a_real_file() -> None:
    # Control for the test below: the helper itself does reach StaticFiles.
    assert send_raw_path("/static/index.html")[0] == 200


@pytest.mark.parametrize(
    "path", ["/static/../main.py", "/static/../../README.md", "/static/..\\main.py"]
)
def test_unnormalized_dot_dot_reaching_the_app_is_refused(path: str) -> None:
    status, body = send_raw_path(path)

    assert status == 404
    assert b"FastAPI" not in body and b"import" not in body
