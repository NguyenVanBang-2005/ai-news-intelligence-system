import pytest

from app.services.text_cleaning import clean_text, truncate


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, ""),
        ("", ""),
        ("   \n\t ", ""),
        ("<p>Hello <b>world</b></p>", "Hello world"),
        ("Tom &amp; Jerry &#8217; &quot;x&quot;", "Tom & Jerry ’ \"x\""),
        ("double&amp;nbsp;encoded", "double encoded"),
        ("a&nbsp;&nbsp;b​﻿c", "a bc"),
        ("<script>evil()</script><style>p{}</style>Text", "Text"),
        ("<p>One</p><p>Two</p>line<br>break", "One\nTwo\nline\nbreak"),
        ("  lots   of \t spaces  ", "lots of spaces"),
        ("<p>soft\n  wrapped</p><pre>line 1\nline 2</pre>", "soft wrapped\nline 1\nline 2"),
        ("Tiếng Việt", "Tiếng Việt"),  # decomposed -> NFC
        ("5 < 6 and 7 > 3", "5 < 6 and 7 > 3"),
    ],
)
def test_clean_text(raw: str | None, expected: str) -> None:
    assert clean_text(raw) == expected


def test_clean_text_single_line() -> None:
    assert clean_text("<p>One</p><p>Two</p>", multiline=False) == "One Two"


def test_truncate_on_word_boundary() -> None:
    assert truncate("short", 10) == "short"
    assert truncate("alpha beta gamma", 12) == "alpha beta…"
