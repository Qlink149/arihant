"""Tidy a person's name when a form sends the FULL name into both First and Last name.

Meta forms (via Zapier) often map "Full Name" into both boxes, giving "Thiru" + "Thiru"
or "Anju Bagri Damani" + "Damani". The CRM then shows "Thiru Thiru". Only exact repeats
are fixed; a name is never invented or shortened beyond removing the repeat.
"""

from __future__ import annotations

import re
from typing import Tuple


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def tidy_person_name(first: str, last: str) -> Tuple[str, str]:
    """Return (first, last) with an exactly repeated surname removed.

    * "Thiru", "Thiru"                      -> "Thiru", ""
    * "Anju Bagri Damani", "Anju Bagri Damani" -> "Anju Bagri", "Damani" (full name split once)
    * "Anju Bagri Damani", "Damani"         -> "Anju Bagri", "Damani"
    * "Ravi", "Kumar" / "Ram", "Ramesh"     -> unchanged
    """
    f, l = _clean(first), _clean(last)
    if not f or not l:
        return f, l
    fl, ll = f.casefold(), l.casefold()
    if fl == ll:
        parts = f.rsplit(" ", 1)
        if len(parts) == 2:
            return parts[0], parts[1]  # a full name sent twice: split once
        return f, ""  # a single word sent twice: keep one
    suffix = " " + ll
    if fl.endswith(suffix) and len(f.split()) > len(l.split()):
        return f[: len(f) - len(suffix)].strip(), l  # surname already inside the first name
    return f, l
