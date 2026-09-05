from __future__ import annotations

import html
from html.parser import HTMLParser
from urllib.parse import urlparse

_DROP_SUBTREE = frozenset({"script", "noscript", "iframe", "frame", "frameset",
                           "object", "embed", "applet", "template"})
_DROP_TAG_ONLY = frozenset({"base", "link", "meta", "form", "button", "input",
                            "select", "textarea", "option"})
_VOID = frozenset({"area", "br", "col", "embed", "hr", "img", "input", "link",
                   "meta", "param", "source", "track", "wbr"})
_URL_ATTRS = frozenset({"href", "src", "action", "formaction", "background",
                        "poster", "cite", "longdesc", "usemap", "data",
                        "srcset", "xlink:href"})
_SAFE_SCHEMES = frozenset({"http", "https", "mailto", "tel", "cid", "data", ""})
_SAFE_DATA_PREFIX = "data:image/"


def _is_safe_url(value: str) -> bool:
    stripped = value.strip().replace("\x00", "")
    lowered = stripped.lower()
    if lowered.startswith("data:"):
        return lowered.startswith(_SAFE_DATA_PREFIX)
    try:
        scheme = urlparse(stripped).scheme.lower()
    except ValueError:
        return False
    return scheme in _SAFE_SCHEMES


class HtmlScrubber(HTMLParser):
    """Rebuilds an HTML document, emitting only inert markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._suppress_depth = 0
        self._raw_text_depth = 0

    def result(self) -> str:
        return "".join(self._out)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, self_closing=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, self_closing=True)

    def _start(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
        self_closing: bool,
    ) -> None:
        if tag in _DROP_SUBTREE:
            if not self_closing:
                self._suppress_depth += 1
            return
        if self._suppress_depth or tag in _DROP_TAG_ONLY:
            return
        if tag == "style":
            self._raw_text_depth += 1

        rendered = "".join(self._attr(name, value) for name, value in attrs)
        closer = " />" if self_closing and tag in _VOID else ">"
        self._out.append(f"<{tag}{rendered}{closer}")

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROP_SUBTREE:
            self._suppress_depth = max(0, self._suppress_depth - 1)
            return
        if self._suppress_depth or tag in _DROP_TAG_ONLY or tag in _VOID:
            return
        if tag == "style":
            self._raw_text_depth = max(0, self._raw_text_depth - 1)
        self._out.append(f"</{tag}>")

    @staticmethod
    def _attr(name: str, value: str | None) -> str:
        lowered = name.lower()
        if lowered.startswith("on") or lowered in ("srcdoc", "http-equiv"):
            return ""
        if value is None:
            return f" {lowered}"
        if lowered in _URL_ATTRS and not _is_safe_url(value):
            return ""
        return f' {lowered}="{html.escape(value, quote=True)}"'

    def handle_data(self, data: str) -> None:
        if self._suppress_depth:
            return
        self._out.append(data if self._raw_text_depth else html.escape(data, quote=False))

    def handle_comment(self, data: str) -> None:
        return
