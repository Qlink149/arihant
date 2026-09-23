"""Environment switches for SLA rule rollouts.

Defaults are fail-closed for Phase 3 so a deploy cannot mass-fire new ladders.
Phase 2 rules stay on unless SLA_PHASE2_RULES_ENABLED is explicitly false
(only needed when those rules are not yet live in production).
"""
from __future__ import annotations

import os


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def phase3_rules_enabled() -> bool:
    return _env_flag("SLA_PHASE3_RULES_ENABLED", False)


def phase2_rules_enabled() -> bool:
    return _env_flag("SLA_PHASE2_RULES_ENABLED", True)
