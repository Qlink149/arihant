"""MCUBE recording URL normalization."""

from __future__ import annotations

from urllib.parse import urlparse


def _basename_from_url(url: str) -> str:
    path = (urlparse(url).path or "").rstrip("/")
    if not path:
        return ""
    return path.rsplit("/", 1)[-1]


def normalize_mcube_recording_url(raw: str) -> tuple[str, str]:
    """
    Return (recording_url, recording_filename).
    URL is set only for absolute http(s) links; bare filenames stay filename-only.
    """
    value = (raw or "").strip()
    if not value:
        return "", ""

    lower = value.lower()
    if lower.startswith("http://") or lower.startswith("https://"):
        return value, _basename_from_url(value) or value

    return "", value
