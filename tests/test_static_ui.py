"""Public UI (/) and admin UI (/admin/): pages served, referenced files served, and the
front-end rules checked by reading the code (no browser, no Node).

Public scripts are app.js and app/static/js/; admin scripts are app/static/admin/.
"""

import re

import pytest
from fastapi.testclient import TestClient

from app.core.security_headers import CONTENT_SECURITY_POLICY
from app.main import STATIC_DIR, app

ADMIN_DIR = STATIC_DIR / "admin"
PUBLIC_JS = sorted((STATIC_DIR / "js").rglob("*.js")) + [STATIC_DIR / "app.js"]
ADMIN_JS = sorted(ADMIN_DIR.rglob("*.js"))
ALL_JS = PUBLIC_JS + ADMIN_JS
HTML_FILES = [STATIC_DIR / "index.html", ADMIN_DIR / "index.html"]
ALL_CODE = ALL_JS + HTML_FILES

FORBIDDEN = [
    "innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function",
    "localStorage", "sessionStorage", "document.cookie", "XMLHttpRequest", "sendBeacon",
]
ADMIN_ONLY_PATHS = ("/ingestion", "/ai/process")
CHANGING_METHOD = re.compile(r'method:\s*"(POST|PUT|PATCH|DELETE)"')
# `import { ..., request, ... } from "./api.js"` (or "../api.js", "../js/api.js", "./admin-api.js").
IMPORTS_REQUEST = re.compile(
    r'import \{[^}]*\b(request|adminRequest)\b[^}]*\} from "(\.\.?/)+(js/)?(api|admin-api)\.js"'
)


def read(path) -> str:
    return path.read_text(encoding="utf-8")


def name(path) -> str:
    return path.relative_to(STATIC_DIR).as_posix()


@pytest.fixture
def web() -> TestClient:
    """A client without a database: these paths never touch one."""
    return TestClient(app)


@pytest.mark.parametrize("path", ["/", "/admin/"])
def test_pages_are_served_as_html_with_the_csp(web: TestClient, path: str) -> None:
    response = web.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["Content-Security-Policy"] == CONTENT_SECURITY_POLICY


@pytest.mark.parametrize("page", ["/", "/admin/"])
def test_every_file_a_page_references_is_served(web: TestClient, page: str) -> None:
    html = web.get(page).text
    references = re.findall(r'(?:src|href)="(/static/[^"]+)"', html)

    assert any(ref.endswith(".js") for ref in references)
    for reference in references:
        assert web.get(reference).status_code == 200, reference


@pytest.mark.parametrize("path", ALL_JS, ids=name)
def test_every_relative_import_exists(path) -> None:
    for target in re.findall(r'from\s+"(\.{1,2}/[^"]+)"', read(path)):
        assert (path.parent / target).resolve().is_file(), f"{name(path)} imports {target}"


@pytest.mark.parametrize("path", ALL_CODE, ids=name)
def test_front_end_rules(path) -> None:
    source = read(path)

    for forbidden in FORBIDDEN:
        assert forbidden not in source, f"{name(path)} contains {forbidden}"
    assert not re.search(r"\.style\b", source), f"{name(path)} touches element.style"
    assert "console.log" not in source


@pytest.mark.parametrize("path", HTML_FILES, ids=name)
def test_pages_have_no_inline_code_or_cdn(path) -> None:
    html = read(path)

    assert not re.search(r"<style\b|\sstyle\s*=|\son[a-z]+\s*=", html, re.IGNORECASE)
    assert not re.search(r"<script(?![^>]*\ssrc=)[^>]*>", html), "inline <script>"
    assert not re.search(r'(?:src|href)="(?:https?:)?//', html), "external file"


@pytest.mark.parametrize("path", PUBLIC_JS, ids=name)
def test_public_scripts_hold_no_admin_actions(path) -> None:
    source = read(path)

    assert "X-Admin-Token" not in source
    for admin_path in ADMIN_ONLY_PATHS:
        assert admin_path not in source, f"{name(path)} calls {admin_path}"
    if "/api/v1/sources" in source:
        assert not CHANGING_METHOD.search(source), f"{name(path)} changes sources"


def test_only_api_js_calls_fetch_and_it_sends_the_csrf_header() -> None:
    callers = [name(path) for path in ALL_JS if "fetch(" in read(path)]
    api = read(STATIC_DIR / "js" / "api.js")

    assert callers == ["js/api.js"]
    assert 'export const CSRF_HEADER = "X-Requested-With";' in api
    assert 'export const CSRF_HEADER_VALUE = "ainis";' in api
    assert "[CSRF_HEADER]: CSRF_HEADER_VALUE" in api


@pytest.mark.parametrize("path", [p for p in ALL_JS if CHANGING_METHOD.search(read(p))], ids=name)
def test_every_changing_call_goes_through_request(path) -> None:
    # A POST/PUT/PATCH/DELETE is an option of request() or adminRequest(), which wraps it.
    source = read(path)

    assert re.search(IMPORTS_REQUEST, source), name(path)
    assert "fetch(" not in source
    assert "return await request(path, options);" in read(ADMIN_DIR / "admin-api.js")


def test_password_fields_use_the_right_autocomplete() -> None:
    dialog = read(STATIC_DIR / "js" / "auth-dialog.js")

    assert 'type: "password"' in dialog
    assert 'autocomplete: "current-password"' in dialog
    assert 'autocomplete: "new-password"' in dialog
    for path in ALL_JS:
        for line in read(path).splitlines():
            assert not ("console." in line and "password" in line.lower()), name(path)


def test_no_token_input_anywhere() -> None:
    for path in ALL_CODE:
        assert "token" not in read(path).lower(), name(path)


def test_public_page_shows_the_account_bar() -> None:
    index = read(STATIC_DIR / "index.html")
    app_js = read(STATIC_DIR / "app.js")
    account = read(STATIC_DIR / "js" / "account-bar.js")

    assert 'id="account"' in index
    assert 'startAccountBar(document.getElementById("account"));' in app_js
    assert 'const ADMIN_PATH = "/admin/";' in account
    assert 'user.role === "admin"' in account


def test_admin_page_gates_on_the_role() -> None:
    admin = read(ADMIN_DIR / "admin.js")

    assert 'const LOGIN_NEEDED = "Log in as an administrator";' in admin
    assert 'const ROLE_NEEDED = "Administrator role required";' in admin
    assert 'if (user.role !== "admin") return showGate(ROLE_NEEDED' in admin
    assert "onSessionLost(" in admin


def test_admin_api_errors_send_back_to_log_in() -> None:
    admin_api = read(ADMIN_DIR / "admin-api.js")

    lost = "if (error?.status === 401 || error?.status === 403) sessionLostHandler(error);"
    assert lost in admin_api
    assert "return detailText(error) ?? errorMessage(error);" in admin_api


def test_ai_job_is_polled_until_finished() -> None:
    ai = read(ADMIN_DIR / "ai-process-admin.js")

    assert 'const FINISHED = new Set(["succeeded", "failed"]);' in ai
    assert 'adminRequest(PROCESS_PATH, { method: "POST", body: {} })' in ai
    assert "while (!FINISHED.has(job.status))" in ai
