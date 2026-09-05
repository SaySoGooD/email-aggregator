"""Turns an email's own HTML into something safe to render (CSP + a parser-based scrub)."""

from __future__ import annotations

import html

from src.adapter.security.html_scrubber import HtmlScrubber


def scrub(markup: str) -> str:
    """Strip active content from an email body, keeping its visible markup."""
    scrubber = HtmlScrubber()
    try:
        scrubber.feed(markup)
        scrubber.close()
    except AssertionError:
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
        "style-src 'unsafe-inline' data:",
    ]
    if allow_remote:
        directives += ["img-src http: https: data: cid:", "font-src http: https: data:"]
    else:
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
    return any(
        marker in lowered
        for marker in ('src="http', "src='http", "src=http",
                       'background="http', "background='http", "url(http")
    )
