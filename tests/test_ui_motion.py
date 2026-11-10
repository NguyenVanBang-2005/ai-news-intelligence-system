"""Design system and motion rules of the web UI, checked by reading app/static as text.

Every CSS, JS and HTML file under app/static is covered. No browser and no Node.
"""

import re

import pytest
from fastapi.testclient import TestClient

from app.core.security_headers import CONTENT_SECURITY_POLICY, SECURITY_HEADERS
from app.main import STATIC_DIR, app

CSS_FILES = sorted(STATIC_DIR.rglob("*.css"))
JS_FILES = sorted(STATIC_DIR.rglob("*.js"))
HTML_FILES = sorted(STATIC_DIR.rglob("*.html"))
ALL_FILES = CSS_FILES + JS_FILES + HTML_FILES
STYLE = (STATIC_DIR / "style.css").read_text(encoding="utf-8")

# Only these animations may loop: skeleton shimmer, the busy spinner and the running job bar.
LOOPING = {"shimmer", "spin", "job-run"}
MAX_MS = 320
# Properties that move the layout; none of them may be animated or transitioned.
LAYOUT_PROPERTIES = ("width", "height", "top", "left", "right", "bottom", "margin", "padding",
                     "inset", "max-height", "max-width", "all")
# The http(s) strings allowed in scripts: XML namespace names, a form placeholder, a comment.
ALLOWED_URLS = {"http://www.w3.org/2000/svg", "https://example.com/feed.xml", "http://", "https://"}


def read(path) -> str:
    return path.read_text(encoding="utf-8")


def name(path) -> str:
    return path.relative_to(STATIC_DIR).as_posix()


def declarations(css: str, prop: str) -> list[str]:
    """Values of every `prop:` declaration (multi-line values included)."""
    return [m.group(1) for m in re.finditer(rf"(?<![-\w]){prop}\s*:\s*([^;{{}}]+);", css)]


def keyframes(css: str) -> dict[str, str]:
    """{name: body} of every @keyframes block (bodies hold one level of braces)."""
    pattern = r"@keyframes\s+([\w-]+)\s*\{((?:[^{}]*\{[^{}]*\})*[^{}]*)\}"
    return {m.group(1): m.group(2) for m in re.finditer(pattern, css)}


def to_ms(value: str) -> float:
    return float(value[:-2]) if value.endswith("ms") else float(value[:-1]) * 1000


def root_vars() -> dict[str, str]:
    root = re.search(r":root\s*\{([^}]*)\}", STYLE).group(1)
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", root))


def contrast(fg: str, bg: str) -> float:
    def luminance(hex_color: str) -> float:
        channels = [int(hex_color.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    high, low = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (high + 0.05) / (low + 0.05)


# --- design variables -------------------------------------------------------------------


def test_design_variables_exist() -> None:
    variables = root_vars()

    assert variables["--duration-fast"].strip() == "120ms"
    assert variables["--duration-base"].strip() == "200ms"
    assert variables["--duration-slow"].strip() == "320ms"
    assert variables["--ease"].strip().startswith("cubic-bezier(")
    assert variables["--stagger-step"].strip() == "40ms"
    for prefix in ("--color-", "--space-", "--radius-", "--shadow-", "--font-size-"):
        assert any(key.startswith(prefix) for key in variables), prefix
    assert "system-ui" in variables["--font-family"]
    # Exactly one easing curve in the whole stylesheet.
    assert len(set(re.findall(r"cubic-bezier\([^)]*\)", STYLE))) == 1


@pytest.mark.parametrize(
    ("fg", "bg"),
    [
        ("--color-text", "--color-bg"),
        ("--color-text-muted", "--color-bg"),
        ("--color-text-muted", "--color-surface"),
        ("--color-primary", "--color-surface"),
        ("--color-primary", "--color-primary-soft"),
        ("--color-success", "--color-success-soft"),
        ("--color-warning", "--color-warning-soft"),
        ("--color-danger", "--color-danger-soft"),
        ("--color-success", "--color-surface"),
    ],
)
def test_text_colors_meet_wcag_aa(fg: str, bg: str) -> None:
    variables = root_vars()
    color = lambda key: re.match(r"#[0-9a-fA-F]{6}", variables[key].strip()).group(0)  # noqa: E731

    assert contrast(color(fg), color(bg)) >= 4.5, f"{fg} on {bg}"


# --- motion rules -----------------------------------------------------------------------


def test_reduced_motion_turns_everything_off() -> None:
    blocks = re.split(r"@media\s*\(prefers-reduced-motion:\s*reduce\)", STYLE)
    assert len(blocks) > 1
    last = blocks[-1]
    assert "animation: none !important;" in last
    assert "transition: none !important;" in last
    assert re.search(r"\*,\s*\*::before,\s*\*::after\s*\{", last)


def test_transitions_never_touch_layout_properties() -> None:
    for value in declarations(STYLE, "transition") + declarations(STYLE, "transition-property"):
        for item in value.split(","):
            words = item.split()
            if not words or words[0] == "none":
                continue
            assert words[0] not in LAYOUT_PROPERTIES, f"transition on {words[0]}"
            assert words[0] in {"transform", "opacity", "box-shadow", "background-color",
                                "border-color", "color"}, item


def test_keyframes_only_move_transform_and_opacity() -> None:
    frames = keyframes(STYLE)
    assert {"rise-in", "item-in", "dialog-in", "bar-grow", "toast-in", "shimmer"} <= set(frames)
    for frame_name, body in frames.items():
        properties = set(re.findall(r"([\w-]+)\s*:", body))
        assert properties <= {"transform", "opacity"}, f"@keyframes {frame_name}: {properties}"


def test_animations_are_short_and_only_known_ones_loop() -> None:
    frames = keyframes(STYLE)
    for value in declarations(STYLE, "animation"):
        if value.strip().startswith("none"):
            continue
        anim_name = value.split()[0]
        assert anim_name in frames, f"unknown animation {anim_name}"
        if "infinite" in value:
            assert anim_name in LOOPING, f"{anim_name} loops"
            continue
        for duration in re.findall(r"(?<![\w-])(\d*\.?\d+m?s)\b", value):
            assert to_ms(duration) <= MAX_MS, value
        for var in re.findall(r"var\((--duration-[\w-]+)\)", value):
            assert to_ms(root_vars()[var].strip()) <= MAX_MS
    for value in declarations(STYLE, "transition"):
        for duration in re.findall(r"(?<![\w-])(\d*\.?\d+m?s)\b", value):
            assert to_ms(duration) <= MAX_MS, value


def test_dialogs_scale_in_and_backdrops_fade() -> None:
    frames = keyframes(STYLE)

    assert "scale(0.97)" in frames["dialog-in"] and "scale(1)" in frames["dialog-in"]
    assert re.search(r"\.dialog \{[^}]*animation: dialog-in", STYLE)
    assert re.search(r"\.dialog-backdrop \{[^}]*animation: fade-in", STYLE)


def test_lists_stagger_by_nth_child_for_eight_items() -> None:
    pattern = (r":nth-child\((n\+)?(\d+)\) \{ "
               r"animation-delay: calc\((\d) \* var\(--stagger-step\)\); \}")
    delays = re.findall(pattern, STYLE)
    steps = [int(step) for _, _, step in delays]

    assert steps == list(range(1, 8))  # items 2..8 wait 40..280 ms; the rest wait like item 8
    assert delays[-1][0] == "n+"
    for script in JS_FILES:
        assert "animationDelay" not in read(script), name(script)


def test_bars_grow_with_scale_x() -> None:
    assert "scaleX(0)" in keyframes(STYLE)["bar-grow"]
    assert re.search(r"\.meter,\s*\.trend-bar \{[^}]*animation: bar-grow", STYLE)


def test_job_progress_has_a_class_per_state() -> None:
    ai = read(STATIC_DIR / "admin" / "ai-process-admin.js")

    for state in ("queued", "running", "done", "failed"):
        assert f".job-progress-{state} .job-progress-bar" in STYLE
    assert 'progress.className = `job-progress job-progress-${suffix}`;' in ai
    assert 'role: "progressbar"' in ai


def test_tab_change_cross_fades_with_a_class() -> None:
    router = read(STATIC_DIR / "js" / "router.js")

    assert 'root.classList.add("route-leaving");' in router
    assert "prefers-reduced-motion: reduce" in router
    assert ".app.route-leaving > * { animation: fade-out" in STYLE


def test_toasts_slide_in_and_hide_by_class() -> None:
    toast = read(STATIC_DIR / "js" / "toast.js")

    assert 'role: tone === "error" ? "alert" : "status"' in toast
    assert '"aria-live": "polite"' in toast
    assert 'toast.classList.add("toast-leaving");' in toast
    assert "setTimeout(" in toast
    assert re.search(r"\.toast \{[^}]*animation: toast-in", STYLE)
    assert ".toast-leaving" in STYLE


def test_loading_is_a_skeleton_and_empty_states_have_an_icon() -> None:
    components = read(STATIC_DIR / "js" / "components.js")

    assert 'className: "state state-loading skeleton", role: "status"' in components
    assert 'svgIcon("icon-empty", "state-empty-icon")' in components
    for page in HTML_FILES:
        html = read(page)
        assert '<symbol id="icon-empty"' in html, name(page)
        assert '<svg class="sprite" aria-hidden="true"' in html, name(page)


def test_busy_buttons_show_a_css_spinner() -> None:
    dom = read(STATIC_DIR / "js" / "dom.js")

    assert '.btn[aria-busy="true"]::before' in STYLE
    assert 'button.setAttribute("aria-busy", "true");' in dom


def test_touch_targets_and_focus_ring() -> None:
    assert ".btn { min-height: 40px; }" in STYLE
    assert ".nav-link { display: inline-flex; align-items: center; min-height: 40px; }" in STYLE
    assert re.search(r":focus-visible \{\s*outline: 3px solid var\(--color-focus\);", STYLE)


# --- forbidden code, every file in app/static -------------------------------------------


@pytest.mark.parametrize("path", ALL_FILES, ids=name)
def test_no_forbidden_strings(path) -> None:
    text = read(path)

    for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
                      "localStorage", "sessionStorage", "document.cookie"):
        assert forbidden not in text, f"{name(path)}: {forbidden}"
    if path.suffix != ".css":
        assert not re.search(r"\.style\.", text), f"{name(path)}: element.style"
        assert not re.search(r"\bstyle\s*=", text), f"{name(path)}: style attribute"


@pytest.mark.parametrize("path", ALL_FILES, ids=name)
def test_nothing_is_loaded_from_another_site(path) -> None:
    text = read(path)

    if path.suffix == ".css":
        assert "@import" not in text
        assert not re.search(r"url\(\s*['\"]?(https?:)?//", text)
    elif path.suffix == ".html":
        assert not re.search(r"(?:src|href)\s*=\s*\"(?:https?:)?//", text)
    else:
        assert not re.search(r"(?:from|import\()\s*[\"'](?:https?:)?//", text)
        for url in re.findall(r"https?://[^\s\"'`)]*", text):
            assert url in ALLOWED_URLS, f"{name(path)}: {url}"


# --- pages are still served with their security headers ---------------------------------


@pytest.mark.parametrize("page", ["/", "/admin/"])
def test_pages_are_200_with_security_headers(page: str) -> None:
    response = TestClient(app).get(page)

    assert response.status_code == 200
    assert response.headers["Content-Security-Policy"] == CONTENT_SECURITY_POLICY
    for header, value in SECURITY_HEADERS.items():
        assert response.headers[header] == value
