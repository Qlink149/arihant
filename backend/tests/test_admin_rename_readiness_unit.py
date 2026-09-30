"""batch3(item5): rename readiness for the "Admin" account (Roshni's login).

Proves that renaming the fixture user's display name from "Admin" to
"Roshni" does not break: (1) WhatsApp unknown-lead admin assignment
(whatsapp_service.resolve_admin_wa_assignee), and (2) project-pool
assignment for Melange/Vipassana (assignment_router.resolve_users_by_emails,
the function every pool in project_assignment_pools.py resolves through).
Both already identify the account by email, not display name - this test
is the proof that ground rule asked for, run against a renamed fixture.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import crm.services.whatsapp_service as wa_service
import crm.services.assignment_router as router
from crm.services.project_assignment_pools import ROSHNI_EMAIL, get_pool

RENAMED_FULL_NAME = "Roshni"  # was "Admin"


def _renamed_admin_doc():
    return {
        "id": "670d7fd1-3185-5ba9-b6bf-b47bab43e72a",
        "full_name": RENAMED_FULL_NAME,
        "email": ROSHNI_EMAIL,
        "role": "admin",
        "is_active": True,
    }


def test_resolve_admin_wa_assignee_unaffected_by_display_name_rename():
    async def _run():
        mock_db = MagicMock()
        mock_db.users.find_one = AsyncMock(return_value=_renamed_admin_doc())
        with patch.object(wa_service, "db", mock_db):
            admin = await wa_service.resolve_admin_wa_assignee()
        assert admin is not None
        assert admin["id"] == "670d7fd1-3185-5ba9-b6bf-b47bab43e72a"
        # The lookup query itself must be email-based - a full_name filter
        # would never have matched this renamed fixture.
        query = mock_db.users.find_one.call_args.args[0]
        assert "full_name" not in query
        assert "email" in query

    asyncio.run(_run())


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    async def to_list(self, limit):
        return self._rows[:limit]


def test_melange_and_vipassana_pools_resolve_by_email_after_rename():
    async def _run():
        mock_db = MagicMock()
        mock_db.users.find = MagicMock(return_value=_FakeCursor([_renamed_admin_doc()]))
        with patch.object(router, "db", mock_db):
            for project_key in ("melange", "vipassana"):
                pool = get_pool(project_key)
                emails = list(pool["primary"])
                resolved = await router.resolve_users_by_emails(emails)
                assert ROSHNI_EMAIL.lower() in resolved
                assert resolved[ROSHNI_EMAIL.lower()]["id"] == "670d7fd1-3185-5ba9-b6bf-b47bab43e72a"

    asyncio.run(_run())


def test_admin_wa_assignee_email_constant_matches_pool_email():
    """Both live lookups key off the same address - one identity, one place."""
    assert wa_service.ADMIN_WA_ASSIGNEE_EMAIL.lower() == ROSHNI_EMAIL.lower()
