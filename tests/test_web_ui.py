"""The web UI in app/static: CSP, files served with the right type, logo, and safe-markup rules.

Plain TestClient requests and file reads only; no browser and no Node.
"""

import re
import struct
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from app.core.security_headers import CONTENT_SECURITY_POLICY
from app.main import STATIC_DIR, app

INDEX_HTML = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
JS_FILES = sorted(STATIC_DIR.rglob("*.js"))
JS_DIR_FILES = sorted((STATIC_DIR / "js").rglob("*.js"))
LOGO_PATH = "/static/img/logo.png"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Both are JavaScript MIME types for browsers; which one Python picks depends on the OS.
JAVASCRIPT_TYPES = ("text/javascript", "application/javascript")
FORBIDDEN_IN_JS = [
    "innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
    'setAttribute("style"', "setAttribute('style'", "cssText",
]


@pytest.fixture
def web() -> TestClient:
    """A client without a database: these paths never touch one."""
    return TestClient(app)


class TagCollector(HTMLParser):
    """Collects (tag, attributes) pairs and the text inside each <script>."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.script_texts: list[str] = []
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        self._in_script = tag == "script"
        if self._in_script:
            self.script_texts.append("")

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False

    def handle_data(self, data):
        if self._in_script:
            self.script_texts[-1] += data


def parse_index() -> TagCollector:
    collector = TagCollector()
    collector.feed(INDEX_HTML)
    return collector


def static_url(path) -> str:
    return "/static/" + path.relative_to(STATIC_DIR).as_posix()


# --- Content-Security-Policy -------------------------------------------------------------


def test_csp_value() -> None:
    assert CONTENT_SECURITY_POLICY == (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; "
        "frame-ancestors 'none'; object-src 'none'"
    )
    assert "unsafe-inline" not in CONTENT_SECURITY_POLICY
    assert "unsafe-eval" not in CONTENT_SECURITY_POLICY


@pytest.mark.parametrize("path", ["/", "/static/app.js", "/static/style.css", LOGO_PATH])
def test_web_ui_has_the_csp(web: TestClient, path: str) -> None:
    response = web.get(path)

    assert response.status_code == 200
    assert response.headers["Content-Security-Policy"] == CONTENT_SECURITY_POLICY


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json", "/api/v1/health"])
def test_docs_and_api_have_no_csp(web: TestClient, path: str) -> None:
    response = web.get(path)

    assert response.status_code == 200
    assert "Content-Security-Policy" not in response.headers


# --- static files ------------------------------------------------------------------------


def test_stylesheet_is_served_as_css(web: TestClient) -> None:
    response = web.get("/static/style.css")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")


@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.name)
def test_every_script_is_served_as_javascript(web: TestClient, path) -> None:
    response = web.get(static_url(path))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(JAVASCRIPT_TYPES)


def test_the_expected_modules_exist() -> None:
    names = {p.relative_to(STATIC_DIR).as_posix() for p in JS_FILES}
    assert {"app.js", "js/api.js", "js/dom.js", "js/format.js", "js/router.js",
            "js/components.js", "js/pages/search.js", "js/trending.js", "js/drawer.js",
            "js/pages/search-results.js", "js/pages/trending-ui.js",
            "js/pages/article-drawer.js", "js/focus-trap.js", "js/admin-token.js",
            "js/confirm-dialog.js", "js/pages/sources.js", "js/pages/admin-access.js",
            "js/pages/rescan.js", "js/pages/source-form.js", "js/pages/source-list.js",
            "js/pages/source-status.js", "js/pages/classified-list.js"} <= names


def test_every_static_reference_in_index_exists() -> None:
    references = re.findall(r'(?:src|href)="(/static/[^"]+)"', INDEX_HTML)

    assert "/static/style.css" in references and "/static/app.js" in references
    for reference in references:
        assert (STATIC_DIR / reference.removeprefix("/static/")).is_file(), reference


@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.name)
def test_every_relative_import_exists(path) -> None:
    imports = re.findall(r'from\s+"(\.{1,2}/[^"]+)"', path.read_text(encoding="utf-8"))

    for target in imports:
        assert (path.parent / target).resolve().is_file(), f"{path.name} imports {target}"


# --- logo --------------------------------------------------------------------------------


def png_size(data: bytes) -> tuple[int, int]:
    """Width and height from the IHDR chunk, which always follows the 8-byte signature."""
    assert data[12:16] == b"IHDR"
    return struct.unpack(">II", data[16:24])


def logo_tag() -> dict[str, str | None]:
    logos = [attrs for tag, attrs in parse_index().tags
             if tag == "img" and attrs.get("src") == LOGO_PATH]
    assert len(logos) == 1, "index.html needs exactly one logo <img>"
    return logos[0]


def test_logo_is_served_as_png(web: TestClient) -> None:
    response = web.get(LOGO_PATH)

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(PNG_SIGNATURE)


def test_logo_tag_has_alt_width_and_height() -> None:
    attrs = logo_tag()

    assert (attrs.get("alt") or "").strip()
    assert attrs.get("width") and attrs.get("height")


def test_logo_tag_size_matches_the_png(web: TestClient) -> None:
    width, height = png_size(web.get(LOGO_PATH).content)
    attrs = logo_tag()

    assert (width, height) == (280, 58)
    assert (int(attrs["width"]), int(attrs["height"])) == (width, height)


# --- no inline code or style -------------------------------------------------------------


def test_index_has_no_inline_script() -> None:
    page = parse_index()
    scripts = [attrs for tag, attrs in page.tags if tag == "script"]

    assert scripts and all(attrs.get("src") for attrs in scripts)
    assert all(text.strip() == "" for text in page.script_texts)


def test_index_has_no_inline_style_or_handlers() -> None:
    assert not re.search(r"<style\b", INDEX_HTML, re.IGNORECASE)
    assert not re.search(r"\sstyle\s*=", INDEX_HTML, re.IGNORECASE)
    assert not re.search(r"\son[a-z]+\s*=", INDEX_HTML, re.IGNORECASE)
    assert "onclick=" not in INDEX_HTML.lower()


def test_index_has_an_empty_data_icon() -> None:
    # Stops the browser from requesting /favicon.ico (a 404 in the console).
    icons = [attrs for tag, attrs in parse_index().tags
             if tag == "link" and attrs.get("rel") == "icon"]

    assert icons == [{"rel": "icon", "href": "data:,"}]


def js_constant(path, name: str) -> int:
    match = re.search(rf"export const {name} = (\d+);", path.read_text(encoding="utf-8"))
    assert match, f"{name} not found in {path.name}"
    return int(match.group(1))


def test_search_timeout_is_longer_than_the_default() -> None:
    api = STATIC_DIR / "js" / "api.js"
    search_page = (STATIC_DIR / "js" / "pages" / "search.js").read_text(encoding="utf-8")

    assert js_constant(api, "SEARCH_TIMEOUT_MS") > js_constant(api, "DEFAULT_TIMEOUT_MS")
    assert js_constant(api, "SEARCH_TIMEOUT_MS") >= 60000
    assert "timeoutMs: SEARCH_TIMEOUT_MS" in search_page


@pytest.mark.parametrize("path", JS_DIR_FILES + [STATIC_DIR / "app.js"], ids=lambda p: p.name)
def test_scripts_never_write_html_or_eval(path) -> None:
    source = path.read_text(encoding="utf-8")

    for forbidden in FORBIDDEN_IN_JS:
        assert forbidden not in source, f"{path.name} contains {forbidden}"


# --- admin token and the Sources page ----------------------------------------------------

ALL_JS = JS_DIR_FILES + [STATIC_DIR / "app.js"]
# The only files allowed to name the admin header: api.js sends it, admin-token.js owns the token.
ADMIN_HEADER_FILES = {"api.js", "admin-token.js"}
# The only files allowed to use sessionStorage: the token and the last rescan result.
SESSION_STORAGE_FILES = {"admin-token.js", "rescan.js"}


@pytest.mark.parametrize("path", ALL_JS, ids=lambda p: p.name)
def test_scripts_never_use_local_storage_or_console_log(path) -> None:
    source = path.read_text(encoding="utf-8")

    assert "localStorage" not in source
    assert "console.log" not in source
    assert "document.cookie" not in source


@pytest.mark.parametrize("path", ALL_JS, ids=lambda p: p.name)
def test_only_api_and_token_modules_name_the_admin_header(path) -> None:
    if path.name not in ADMIN_HEADER_FILES:
        assert "X-Admin-Token" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", ALL_JS, ids=lambda p: p.name)
def test_only_token_and_rescan_modules_use_session_storage(path) -> None:
    if path.name not in SESSION_STORAGE_FILES:
        assert "sessionStorage" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", ALL_JS, ids=lambda p: p.name)
def test_scripts_never_use_the_browser_confirm_box(path) -> None:
    source = path.read_text(encoding="utf-8")

    assert "window.confirm" not in source
    assert "confirm(" not in source


def test_rescan_has_its_own_long_timeout() -> None:
    rescan = STATIC_DIR / "js" / "pages" / "rescan.js"

    assert js_constant(rescan, "RESCAN_TIMEOUT_MS") == 180000
    assert "timeoutMs: RESCAN_TIMEOUT_MS" in rescan.read_text(encoding="utf-8")


def test_sources_route_shows_the_sources_page() -> None:
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert "sources: { title: \"Sources\", render: renderSourcesPage }" in app_js


def test_delete_always_asks_first() -> None:
    source_list = (STATIC_DIR / "js" / "pages" / "source-list.js").read_text(encoding="utf-8")

    assert source_list.count('method: "DELETE"') == 1
    assert "permanently deletes all of its articles" in source_list
    # The only path to deleteSource() goes through the confirmation dialog.
    assert len(re.findall(r"(?<!function )deleteSource\(", source_list)) == 1
    assert "if (confirmed) await deleteSource(view, source);" in source_list
