"""Credential-shaped startup values shared by discovery and execution."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

_CREDENTIAL_NAMES = {
    "ACCESS_TOKEN",
    "ACCESS_KEY",
    "API_KEY",
    "APIKEY",
    "AUTH_TOKEN",
    "CLIENT_SECRET",
    "PASSWORD",
    "PASSWD",
    "PRIVATE_KEY",
    "REFRESH_TOKEN",
    "SECRET",
    "SECRET_ACCESS_KEY",
    "TOKEN",
}

_CREDENTIAL_SUFFIXES = tuple(f"_{name}" for name in _CREDENTIAL_NAMES)


def reference_name(value) -> str | None:
    match = _REFERENCE.fullmatch(str(value))
    return match[1] if match else None


def is_credential_name(name: str) -> bool:
    normalized = str(name).upper()
    return normalized in _CREDENTIAL_NAMES or normalized.endswith(_CREDENTIAL_SUFFIXES)


def has_url_credentials(value) -> bool:
    text = str(value)
    try:
        parsed = urlsplit(text)
        return bool(parsed.scheme and parsed.netloc and (parsed.username or parsed.password))
    except ValueError:
        if "://" not in text:
            return False
        authority = text.split("://", 1)[1].split("/", 1)[0]
        return "@" in authority
