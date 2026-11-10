"""XSS / input hardening helpers.

The API only ever returns JSON, but untrusted text is still sanitised on the
way in so that any downstream consumer (admin dashboards, emails, exports)
cannot be tricked into rendering active markup.
"""

from __future__ import annotations

import re
import unicodedata

import bleach

# Control characters that have no place in user supplied text.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Collapse runs of whitespace but keep single newlines.
_WHITESPACE = re.compile(r"[^\S\n]+")

_ALLOWED_TAGS: list[str] = []
_ALLOWED_ATTRS: dict[str, list[str]] = {}


def clean_text(value: str, *, max_length: int | None = None) -> str:
    """Strip markup, control characters and surrounding whitespace.

    ``bleach.clean`` with no allowed tags escapes/strips anything that could
    be interpreted as HTML, which neutralises stored-XSS payloads.
    """
    if not isinstance(value, str):
        raise TypeError("expected a string")

    value = unicodedata.normalize("NFC", value)
    value = _CONTROL_CHARS.sub("", value)
    value = bleach.clean(
        value,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        protocols=[],
        strip=True,
        strip_comments=True,
    )
    value = _WHITESPACE.sub(" ", value).strip()

    if max_length is not None and len(value) > max_length:
        value = value[:max_length].rstrip()
    return value


def clean_optional(value: str | None, *, max_length: int | None = None) -> str | None:
    if value is None:
        return None
    return clean_text(value, max_length=max_length)


def clean_url(value: str | None, *, max_length: int = 1024) -> str | None:
    """Only allow http(s) image URLs; reject javascript:/data: payloads."""
    if value is None or value == "":
        return None
    candidate = value.strip()
    lowered = candidate.lower()
    if not (lowered.startswith("http://") or lowered.startswith("https://")):
        raise ValueError("image_url must start with http:// or https://")
    if len(candidate) > max_length:
        raise ValueError("image_url is too long")
    # Reject characters that could break out of an attribute context.
    if any(ch in candidate for ch in ('"', "'", "<", ">", "`", "\\")):
        raise ValueError("image_url contains illegal characters")
    return candidate


def escape_like(value: str) -> str:
    """Escape LIKE wildcards so a search term is matched literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
