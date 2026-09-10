"""Parse MCUBE duration strings (HH:MM:SS or bare seconds)."""

from __future__ import annotations

import re
from typing import Optional


def parse_duration(value: object) -> Optional[int]:
    """
    Inbound Classic doc sample uses HH:MM:SS; live hangup uses seconds as string ("193").
    Returns non-negative seconds or None.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        sec = int(value)
        return sec if sec >= 0 else None
    s = str(value).strip()
    if not s:
        return None
    if re.fullmatch(r"\d+", s):
        return int(s)
    # HH:MM:SS or H:MM:SS or MM:SS
    parts = s.split(":")
    try:
        if len(parts) == 3:
            h, m, sec = int(parts[0]), int(parts[1]), int(parts[2])
            return h * 3600 + m * 60 + sec
        if len(parts) == 2:
            m, sec = int(parts[0]), int(parts[1])
            return m * 60 + sec
    except ValueError:
        return None
    return None
