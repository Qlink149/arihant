"""Canonical CRM roles and Escalation Queue ACL."""

from __future__ import annotations

from typing import Optional

ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_GENERAL_MANAGER = "general_manager"
ROLE_REP = "rep"

ALL_ROLES = frozenset({ROLE_ADMIN, ROLE_MANAGER, ROLE_GENERAL_MANAGER, ROLE_REP})

# Ops manager + admin + GM — Escalation Queue only (do not reuse for Settings).
ESCALATION_ROLES = frozenset({ROLE_ADMIN, ROLE_MANAGER, ROLE_GENERAL_MANAGER})

# Edit-everywhere / org-wide pipeline (GM is intentionally excluded — like rep).
ORG_EDIT_ROLES = frozenset({ROLE_ADMIN, ROLE_MANAGER})


def normalize_role(role: Optional[str]) -> str:
    return (role or ROLE_REP).strip().lower() or ROLE_REP


def can_access_escalations(role: Optional[str]) -> bool:
    return normalize_role(role) in ESCALATION_ROLES


def can_filter_escalated_leads(role: Optional[str]) -> bool:
    """Virtual Customer ?escalated=true — SOP Manager is general_manager."""
    return normalize_role(role) in {ROLE_ADMIN, ROLE_GENERAL_MANAGER}


def can_see_rnr_call_panel(role: Optional[str]) -> bool:
    return normalize_role(role) in {ROLE_ADMIN, ROLE_GENERAL_MANAGER}


def can_access_sales_dashboard(role: Optional[str]) -> bool:
    return normalize_role(role) in {ROLE_ADMIN, ROLE_GENERAL_MANAGER}


def is_org_editor(role: Optional[str]) -> bool:
    return normalize_role(role) in ORG_EDIT_ROLES


def is_admin_role(role: Optional[str]) -> bool:
    return normalize_role(role) == ROLE_ADMIN


def user_may_authenticate(user: Optional[dict]) -> bool:
    """Inactive non-admin accounts cannot log in or keep a session."""
    if not user:
        return False
    if user.get("is_active") is False and not is_admin_role(user.get("role")):
        return False
    return True
