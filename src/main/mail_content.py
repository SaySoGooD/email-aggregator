"""
Turning an email's own HTML into something safe to render.

The sender controls this markup completely, so it is treated as hostile input.
Two independent layers stand between it and the viewer:

1. A Content-Security-Policy meta tag. This is the control that actually holds:
   it is enforced by the rendering engine itself, it applies to markup this
   module never managed to parse, and it survives being written to a file and
   opened in whatever browser the user has. It denies scripts outright and,
   unless the user asks otherwise, denies remote loads too.
2. A parser-based scrub that removes active elements and attributes before they
   ever reach the renderer. On its own a scrub can always be out-parsed by a
   sufficiently strange document; behind the CSP it is a second wall rather
   than the only one.
"""

from __future__ import annotations

import html
from html.parser import HTMLParser
from urllib.parse import urlparse

# Elements dropped together with everything inside them.
_DROP_SUBTREE = frozenset({"script", "noscript", "iframe", "frame", "frameset",
                           "object", "embed", "applet", "template"})
# Elements dropped while their contents are kept (the text still belongs to the
# message; only the element's own behaviour is unwanted).
_DROP_TAG_ONLY = frozenset({"base", "link", "meta", "form", "button", "input",
                            "select", "textarea", "option"})
# Elements that never have a closing tag.
_VOID = frozenset({"area", "br", "col", "embed", "hr", "img", "input", "link",
                   "meta", "param", "source", "track", "wbr"})
# Attributes carrying a URL, checked against the scheme allowlist below.
_URL_ATTRS = frozenset({"href", "src", "action", "formaction", "background",
                        "poster", "cite", "longdesc", "usemap", "data",
                        "srcset", "xlink:href"})
# javascript:, vbscript:, and file: are the reason this list is an allowlist.
# cid: is how a message references its own inline attachments.
_SAFE_SCHEMES = frozenset({"http", "https", "mailto", "tel", "cid", "data", ""})
# A data: URL is fine for an inline image and not fine for anything else.
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


class _Scrubber(HTMLParser):
    """Rebuilds the document, emitting only inert markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._suppress_depth = 0
        self._raw_text_depth = 0  # inside <style>: contents are CSS, not text

    def result(self) -> str:
        return "".join(self._out)

    # -- element handling ---------------------------------------------

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
        # on* is every inline event handler there is: onclick, onerror, onload,
        # and the ones a future HTML revision adds.
        if lowered.startswith("on") or lowered in ("srcdoc", "http-equiv"):
            return ""
        if value is None:
            return f" {lowered}"
        if lowered in _URL_ATTRS and not _is_safe_url(value):
            return ""
        return f' {lowered}="{html.escape(value, quote=True)}"'

    # -- text handling -------------------------------------------------

    def handle_data(self, data: str) -> None:
        if self._suppress_depth:
            return
        # HTMLParser hands <style> contents over raw; escaping them would break
        # selectors like "a > b". Ordinary text arrives with entities already
        # decoded, so it has to be re-escaped on the way out.
        self._out.append(data if self._raw_text_depth else html.escape(data, quote=False))

    def handle_comment(self, data: str) -> None:
        # Conditional comments are markup to some renderers. Drop them all.
        return


def scrub(markup: str) -> str:
    """Strip active content from an email body, keeping its visible markup."""
    scrubber = _Scrubber()
    try:
        scrubber.feed(markup)
        scrubber.close()
    except AssertionError:
        # HTMLParser can trip on sufficiently malformed input; falling back to
        # fully escaped text shows the message without rendering anything.
        return f"<pre>{html.escape(markup)}</pre>"
    return scrubber.result()


def _policy(allow_remote: bool) -> str:
    """The CSP for a rendered message."""
    directives = [
        "default-src 'none'",
        "script-src 'none'",
        "object-src 'none'",
        "frame-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
        # Emails are styled almost entirely with inline style attributes, which
        # need 'unsafe-inline'. That keyword only ever permits CSS here: scripts
        # are denied by script-src regardless of what style-src allows.
        "style-src 'unsafe-inline' data:",
    ]
    if allow_remote:
        directives += ["img-src http: https: data: cid:", "font-src http: https: data:"]
    else:
        # Blocking remote loads is what stops a tracking pixel from reporting
        # that the message was opened, from where, and when.
        directives += ["img-src data: cid:", "font-src data:"]
    return "; ".join(directives)


def document(
    body_html: str | None,
    body_text: str | None,
    allow_remote: bool = False,
) -> str:
    """Wrap a message body in a full, hardened HTML document."""
    if body_html:
        body = scrub(body_html)
    else:
        escaped = html.escape(body_text or "(empty message)")
        body = f"<pre style='white-space:pre-wrap;font:14px sans-serif'>{escaped}</pre>"
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<meta http-equiv='Content-Security-Policy' content=\"{_policy(allow_remote)}\">"
        "<meta name='referrer' content='no-referrer'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "</head><body style='margin:0'>"
        f"{body}</body></html>"
    )


def has_remote_content(body_html: str | None) -> bool:
    """Whether the message references anything that would be fetched remotely."""
    if not body_html:
        return False
    lowered = body_html.lower()
    # Only loads count. A plain <a href="http://..."> fetches nothing until the
    # user clicks it, so it must not raise the banner on every second message.
    return any(
        marker in lowered
        for marker in ('src="http', "src='http", "src=http",
                       'background="http', "background='http", "url(http")
    )
