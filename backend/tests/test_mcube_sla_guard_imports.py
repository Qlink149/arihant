"""Guard: MCUBE package must never import SLA-mutating lead writers."""

from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN = frozenset(
    {
        "update_lead",
        "_queue_task",
        "_queue_lead_mutation",
        "create_sla_task_for_lead",
    }
)

MCUBE_ROOT = Path(__file__).resolve().parents[1] / "crm" / "services" / "mcube"


def test_mcube_package_forbids_sla_mutating_imports():
    assert MCUBE_ROOT.is_dir(), f"missing {MCUBE_ROOT}"
    offenders = []
    for path in MCUBE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    name = alias.name
                    if name in FORBIDDEN:
                        offenders.append(f"{path.name}: from {node.module} import {name}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[-1] in FORBIDDEN:
                        offenders.append(f"{path.name}: import {alias.name}")
            if isinstance(node, ast.Name) and node.id in FORBIDDEN:
                # Allow string mentions only — Name load of forbidden symbols
                offenders.append(f"{path.name}: name {node.id} line {node.lineno}")
    # Filter false positives: only flag ImportFrom/Import (Name would catch too much)
    import_offenders = [o for o in offenders if "import" in o.lower() or o.startswith(tuple())]
    import_offenders = [o for o in offenders if ": from " in o or ": import " in o]
    assert import_offenders == [], "Forbidden imports in MCUBE package:\n" + "\n".join(import_offenders)
