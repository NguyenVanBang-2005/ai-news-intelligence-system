import html
import re
import unicodedata
from html.parser import HTMLParser

# Tags whose boundaries separate paragraphs; their text must not run together.
_BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt",
    "figcaption", "figure", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header",
    "hr", "li", "ol", "p", "pre", "section", "table", "td", "th", "tr", "ul",
}  # fmt: skip
# Tags whose content is never readable article text.
_SKIP_TAGS = {"script", "style", "noscript", "iframe", "svg", "template"}
# Zero-width and BOM characters that survive copy/paste from CMS editors.
_INVISIBLE = dict.fromkeys(map(ord, "​‌‍⁠﻿­"))
_INLINE_SPACE = re.compile(r"[^\S\n]+")
_ANY_SPACE = re.compile(r"\s+")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self._pre_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._pre_depth += tag == "pre"
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK_TAGS:
            self._pre_depth = max(0, self._pre_depth - (tag == "pre"))
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        # As in a browser, source line wraps are plain spaces outside <pre>;
        # only block tags start a new line.
        self.parts.append(data if self._pre_depth else _ANY_SPACE.sub(" ", data))


def clean_text(raw: str | None, *, multiline: bool = True) -> str:
    """Turn RSS HTML/entity-laden text into plain text.

    Paragraph boundaries are kept as single newlines when ``multiline`` is true, so
    downstream summarizers still see the article structure; everything else collapses
    to single spaces.
    """
    if not raw:
        return ""
    parser = _TextExtractor()
    parser.feed(raw)
    parser.close()
    # A second unescape handles double-encoded feeds such as "&amp;nbsp;".
    text = html.unescape("".join(parser.parts))
    text = unicodedata.normalize("NFC", text).translate(_INVISIBLE).replace("\r", "\n")
    lines = (_INLINE_SPACE.sub(" ", line).strip() for line in text.split("\n"))
    return ("\n" if multiline else " ").join(line for line in lines if line)


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rsplit(" ", 1)[0] + "…"
