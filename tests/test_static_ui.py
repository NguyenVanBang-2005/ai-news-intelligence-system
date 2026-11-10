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


# --- layout of the admin result blocks (CSS read as text) ----------------------------------

STYLE = read(STATIC_DIR / "style.css")


def css_rule(selector: str) -> str:
    """The body of the first top-level rule whose selector is exactly `selector`."""
    match = re.search(rf"(?m)^{re.escape(selector)} \{{([^}}]*)\}}", STYLE)
    assert match, f"no rule for {selector}"
    return match.group(1)


def static_classes(path) -> set[str]:
    """Class names written as plain strings in `className: "..."` (template parts skipped)."""
    names = set()
    for value in re.findall(r'className:\s*"([^"]+)"', read(path)):
        names.update(value.split())
    return names


RESULT_BLOCKS = [ADMIN_DIR / "ingestion-admin.js", ADMIN_DIR / "ai-process-admin.js"]


@pytest.mark.parametrize("path", RESULT_BLOCKS, ids=name)
def test_result_block_classes_exist_in_the_stylesheet(path) -> None:
    for class_name in static_classes(path):
        assert re.search(rf"\.{re.escape(class_name)}\b", STYLE), f"{name(path)}: .{class_name}"


def test_new_layout_classes_exist() -> None:
    for class_name in ("rescan-errors-title-danger", "admin-card", "job-result", "job-status"):
        assert f".{class_name}" in STYLE


def test_stat_grid_wraps_and_stays_in_normal_flow() -> None:
    grid = css_rule(".stat-grid")

    assert "repeat(auto-fit, minmax(min(100%, 150px), 1fr))" in grid
    assert "margin" not in grid  # a negative margin pulled the cards over the button above
    for selector in (".stat-grid", ".stat-card", ".rescan-card"):
        body = css_rule(selector)
        assert "position" not in body and "float" not in body and "height" not in body


def test_long_technical_names_wrap_instead_of_being_cut() -> None:
    for selector in (".stat-field", ".stat-label", ".rescan-summary"):
        assert "overflow-wrap: anywhere" in css_rule(selector)
    assert "min-width: 0" in css_rule(".stat-card")
    assert "overflow-x: auto" in css_rule(".source-list-body")


def test_errors_title_is_red_only_with_errors() -> None:
    ingestion = read(ADMIN_DIR / "ingestion-admin.js")

    assert "color: var(--color-text-muted)" in css_rule(".rescan-errors-title")
    assert "color: var(--color-danger)" in css_rule(".rescan-errors-title-danger")
    assert ('return count > 0 ? "rescan-errors-title rescan-errors-title-danger" '
            ': "rescan-errors-title";') in ingestion
    assert "className: errorsTitleClass(errors.length)" in ingestion


@pytest.mark.parametrize("path", ALL_JS, ids=name)
def test_scripts_set_no_inline_style(path) -> None:
    source = read(path)

    assert not re.search(r"""setAttribute\(\s*["']style""", source)
    assert "cssText" not in source and "style:" not in source


# --- change password dialog and source on/off -----------------------------------------------


def test_change_password_dialog_is_in_both_account_bars() -> None:
    dialog = read(STATIC_DIR / "js" / "password-dialog.js")
    auth = read(STATIC_DIR / "js" / "auth.js")

    assert 'text: "Change password"' in dialog
    assert 'role: "dialog", "aria-modal": "true"' in dialog
    for label in ("Current password", "New password", "Confirm new password"):
        assert f'"{label}"' in dialog
    assert '"current-password"' in dialog and '"new-password"' in dialog
    assert 'if (next !== confirm) return "The new passwords do not match.";' in dialog
    assert "`${AUTH_PATH}/change-password`" in auth
    assert "current_password: currentPassword, new_password: newPassword" in auth
    for path in (STATIC_DIR / "js" / "account-bar.js", ADMIN_DIR / "admin.js"):
        assert "...changePasswordControls()," in read(path), name(path)


def test_change_password_errors_and_notice_are_plain_text() -> None:
    dialog = read(STATIC_DIR / "js" / "password-dialog.js")

    assert 'if (error?.status === 401) return "Your session has ended.' in dialog
    assert "return authErrorText(error);" in dialog  # 400 / 422 / 429 detail via detailText
    assert 'el("p", { className: "banner banner-error", role: "alert", text })' in dialog
    assert 'showToast("Password changed.' in dialog
    for class_name in ("toast", "auth-form", "form-note", "form-message"):
        assert f".{class_name}" in STYLE


def test_admin_sources_have_an_enable_disable_button() -> None:
    sources = read(ADMIN_DIR / "sources-admin.js")

    assert 'const action = source.is_active ? "Disable" : "Enable";' in sources
    assert 'method: "PATCH", body: { is_active: turnOn }' in sources
    assert "adminRequest(`${SOURCES_PATH}/${encodeURIComponent(source.id)}`" in sources
    assert 'button.setAttribute("aria-busy", "true");' in sources
    assert "button.disabled = true;" in sources
    assert 'turnOn ? "Enabling…" : "Disabling…"' in sources
    assert "row.replaceWith(fresh);" in sources
    assert ".btn-toggle" in STYLE
