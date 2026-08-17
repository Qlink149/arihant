"""
In-process live verification for change-tracker fixes.
Runs without a long-lived server; imports the real app + helpers.
"""
from __future__ import annotations

import asyncio
import inspect
import sys
from datetime import timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def main() -> int:
    # 1) imports / no NameError on dormant notification builder
    from crm.api.v1.endpoints import notifications as notif_mod
    from crm.api.v1.endpoints import tasks as tasks_mod
    from crm.api.v1.endpoints import whatsapp as wa_mod
    from crm.constants.lead_status import terminal_exclusion_clause
    from crm.services.sales_dashboard_filters import rnr_metric_clause, build_sales_metric_filter
    from crm.services.lead_filter_views_service import LeadFilterViewFilters
    from crm.services import sla_engine as sla_mod
    from crm.services.sla_engine import build_task_doc
    from crm.utils.helpers import ist_wall_to_utc_dt
    from crm.main import app

    check(
        "terminal_exclusion_clause imported in notifications",
        "terminal_exclusion_clause" in notif_mod.__dict__,
    )

    # 2) OpenAPI routes present
    paths = set(app.openapi().get("paths", {}).keys())
    check("PATCH /api/leads/{lead_id}/context/{entry_index}", "/api/leads/{lead_id}/context/{entry_index}" in paths)
    check("GET /api/escalations", "/api/escalations" in paths)
    brochure = app.openapi()["paths"].get("/api/whatsapp/brochure/{lead_id}", {})
    get_or_post = brochure.get("post") or brochure.get("get") or {}
    params = {p.get("name") for p in (get_or_post.get("parameters") or [])}
    # FastAPI may name path differently
    brochure_paths = [p for p in paths if "brochure" in p]
    check("brochure route exists", bool(brochure_paths), str(brochure_paths))
    # Inspect endpoint signature for project=
    sig = inspect.signature(wa_mod.send_brochure_to_lead)
    check("send_brochure_to_lead has project param", "project" in sig.parameters)

    # 3) RNR clause correctness
    clause = rnr_metric_clause()
    blob = str(clause)
    check("rnr_metric_clause has no original_fw_status", "original_fw_status" not in blob)
    check("rnr_metric_clause has is_rnr / lead_status", "is_rnr" in blob and "lead_status" in blob)
    sales = build_sales_metric_filter("rnr")
    check("sales metric rnr wrapped in $and", "$and" in sales)

    # 4) Saved views keep sales_owners, mine, date_field
    dumped = LeadFilterViewFilters.model_validate(
        {"sales_owners": ["A"], "mine": True, "date_field": "updated"}
    ).model_dump()
    check("saved view sales_owners", dumped["sales_owners"] == ["A"])
    check("saved view mine", dumped["mine"] is True)
    check("saved view date_field", dumped["date_field"] == "updated")

    # 5) IST wall clock: 2026-07-01 11:00 IST -> 05:30 UTC
    utc_dt = ist_wall_to_utc_dt("2026-07-01", "11:00")
    check(
        "IST 11:00 -> UTC 05:30",
        utc_dt.astimezone(timezone.utc).strftime("%H:%M") == "05:30",
        str(utc_dt),
    )

    # 6) SLA engine source has 3600; RNR 48h/15d escalate as tasks only (no ownership transfer)
    src = Path(inspect.getsourcefile(sla_mod)).read_text(encoding="utf-8")
    check("sla reassign uses 3600", "3600" in src and "reassign_1h_at_dt" in src)
    check("sla RNR does not call assign_lead_to_admin", "assign_lead_to_admin" not in src)
    check("sla RNR still has 48h and 15d escalate tasks", '"48h"' in src and '"15d"' in src)

    # 7) Task create uses ist helper in source
    tsrc = Path(inspect.getsourcefile(tasks_mod)).read_text(encoding="utf-8")
    check("tasks.py uses ist_wall_to_utc_dt", "ist_wall_to_utc_dt" in tsrc)
    check("patch_context does not always set recent_note", "if entry_index == len(updates) - 1:" in tsrc)

    # 8) build_task_doc uses IST helper
    bsrc = inspect.getsource(build_task_doc)
    check("build_task_doc uses ist_wall_to_utc_dt", "ist_wall_to_utc_dt" in bsrc)

    # 9) Smoke: _build_auto_notifications does not NameError with empty mocked DB
    async def _smoke_auto():
        from unittest.mock import AsyncMock, MagicMock, patch

        def fake_find(query, projection):
            m = MagicMock()
            m.to_list = AsyncMock(return_value=[])
            m.limit = MagicMock(return_value=m)
            return m

        with patch.object(notif_mod, "db") as mock_db:
            mock_db.leads.find = fake_find
            return await notif_mod._build_auto_notifications({"id": "a", "role": "admin", "full_name": "Admin"})

    try:
        out = asyncio.run(_smoke_auto())
        check("auto notifications smoke (no NameError)", isinstance(out, list), f"n={len(out)}")
    except Exception as exc:  # noqa: BLE001
        check("auto notifications smoke (no NameError)", False, repr(exc))

    print()
    if failures:
        print(f"FAILED ({len(failures)}): {', '.join(failures)}")
        return 1
    print("ALL LIVE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
