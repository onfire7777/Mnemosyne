"""Canonical local workspace paths shared by capture and historical replay."""
from __future__ import annotations

import os
from urllib.parse import unquote, urlsplit


def normalize_workspace(value):
    if not isinstance(value, str) or not value or '\0' in value:
        return None
    if value[:5].casefold() == 'file:':
        try:
            parsed = urlsplit(value)
        except ValueError:
            return None
        if parsed.netloc.casefold() not in {'', 'localhost'} or parsed.query or parsed.fragment:
            return None
        value = unquote(parsed.path)
    if '\0' in value or not os.path.isabs(value):
        return None
    return os.path.normpath(value)
