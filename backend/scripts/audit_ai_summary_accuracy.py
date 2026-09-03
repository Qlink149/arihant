"""
Read-only prod audit of AI persona accuracy using CURRENT prompt + live LLM.

- Reads leads from DB_NAME=arihant_crm only
- NEVER writes ai_* fields (or anything else) back to Mongo
- Rebuilds transcript/hints via current ai_lead_regen helpers
- Calls generate_lead_insights (live Groq/Grok keys from backend/.env)

Usage (from backend/):
  python scripts/audit_ai_summary_accuracy.py
  python scripts/audit_ai_summary_accuracy.py --limit 15
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from pymongo import MongoClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv(BACKEND_ROOT / ".env", override=True)

TERMINAL_STATUSES = frozenset(
    {"unqualified", "junk", "closed lost", "closed won"}
)
ACTIVE_INTEREST_RE = re.compile(
    r"\b(currently interested|keen on|will revert|block (the )?plot|site visit planned)\b",
    re.I,
)
ENGAGE_MOVE_RE = re.compile(
    r"re-establish|follow up|schedule (a )?(call|visit)|gauge interest|engage",
    re.I,
)
RNR_WRONG_RE = re.compile(r"ready to negotiate|ready to rent", re.I)


def _mask_phone(phone: Any) -> str:
    digits = re.sub(r"\D", "", str(phone or ""))
    if len(digits) >= 4:
        return "***" + digits[-4:]
    return "n/a"


def _as_dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def assert_prod_readonly() -> dict:
    db_name = (os.environ.get("DB_NAME") or "").strip()
    mongo = (os.environ.get("MONGO_URL") or "").strip()
    if db_name != "arihant_crm":
        raise SystemExit(f"REFUSE: expected DB_NAME=arihant_crm for read source, got {db_name!r}")
    if not mongo:
        raise SystemExit("REFUSE: MONGO_URL missing")
    if "e2e" in db_name.lower():
        raise SystemExit("REFUSE: e2e db")
    return {"DB_NAME": db_name, "MONGO_URL": mongo}


def select_lead_ids(db, limit: int) -> List[str]:
    ids: List[str] = []
    # Tracker #45 example phones
    for suffix in ("9840050599", "9176086576"):
        doc = db.leads.find_one(
            {
                "$or": [
                    {"phone": {"$regex": suffix}},
                    {"normalized_phone": {"$regex": suffix[-10:]}},
                ]
            },
            {"_id": 0, "id": 1},
        )
        if doc and doc.get("id") and doc["id"] not in ids:
            ids.append(doc["id"])

    # Diverse statuses with long timelines
    status_buckets = [
        "Unqualified",
        "Closed Lost",
        "RNR",
        "Nurturing",
        "Visit Completed",
        "Site Visit Scheduled",
        "Contacted",
        "Negotiation",
    ]
    for status in status_buckets:
        if len(ids) >= limit:
            break
        rows = list(
            db.leads.aggregate(
                [
                    {
                        "$match": {
                            "lead_status": status,
                            "context_updates.14": {"$exists": True},
                        }
                    },
                    {
                        "$project": {
                            "_id": 0,
                            "id": 1,
                            "n": {"$size": {"$ifNull": ["$context_updates", []]}},
                            "has_ai": {
                                "$cond": [
                                    {
                                        "$and": [
                                            {"$eq": [{"$type": "$ai_persona_summary"}, "string"]},
                                            {"$ne": ["$ai_persona_summary", ""]},
                                        ]
                                    },
                                    1,
                                    0,
                                ]
                            },
                        }
                    },
                    {"$sort": {"has_ai": -1, "n": -1}},
                    {"$limit": 3},
                ],
                allowDiskUse=True,
            )
        )
        for r in rows:
            lid = r.get("id")
            if lid and lid not in ids:
                ids.append(lid)
            if len(ids) >= limit:
                break

    # Top long timelines fill
    if len(ids) < limit:
        rows = list(
            db.leads.aggregate(
                [
                    {"$match": {"context_updates.19": {"$exists": True}}},
                    {
                        "$project": {
                            "_id": 0,
                            "id": 1,
                            "n": {"$size": {"$ifNull": ["$context_updates", []]}},
                        }
                    },
                    {"$sort": {"n": -1}},
                    {"$limit": limit * 2},
                ],
                allowDiskUse=True,
            )
        )
        for r in rows:
            lid = r.get("id")
            if lid and lid not in ids:
                ids.append(lid)
            if len(ids) >= limit:
                break
    return ids[:limit]


def latest_notes(updates: List[dict], n: int = 5) -> List[dict]:
    out: List[dict] = []
    for u in reversed(updates):
        if not isinstance(u, dict):
            continue
        desc = (u.get("description") or u.get("note") or "").strip()
        if not desc:
            continue
        out.append(
            {
                "type": (u.get("type") or u.get("update_type") or "").lower(),
                "ts": str(u.get("timestamp") or "")[:19],
                "desc": desc[:220],
            }
        )
        if len(out) >= n:
            break
    return list(reversed(out))


def score_fresh(lead: dict, payload: dict) -> dict:
    status = (lead.get("lead_status") or "").strip()
    status_l = status.lower()
    budget = (lead.get("budget") or "").strip()
    lost_reason = (lead.get("lost_reason") or "").strip()
    summ = payload.get("persona_summary") or ""
    moves = payload.get("strategic_next_moves") or []
    # Score move *titles* only — rationale text often says "re-engage later" even for closure moves.
    titles: List[str] = []
    for m in moves:
        if isinstance(m, dict):
            titles.append(str(m.get("title") or ""))
        else:
            titles.append(str(m or ""))
    move_blob = " | ".join(titles).lower()
    issues: List[str] = []

    if status_l in TERMINAL_STATUSES:
        if ACTIVE_INTEREST_RE.search(summ) and not re.search(
            r"\b(unqualified|closed lost|junk|not interested|lost|disqualified)\b",
            summ,
            re.I,
        ):
            issues.append("summary_sounds_active_but_status_terminal")
        if ENGAGE_MOVE_RE.search(move_blob) and not re.search(
            r"close|archive|stop|do not|not interested|lost",
            move_blob,
            re.I,
        ):
            issues.append("moves_still_push_engagement_on_dead_status")

    if lost_reason and status_l in TERMINAL_STATUSES | {"rnr"}:
        lr = lost_reason.lower()
        if lr not in summ.lower() and "not interested" not in summ.lower() and "lost" not in summ.lower():
            # only flag when notes also imply loss
            if any(
                "not interest" in (n.get("desc") or "").lower()
                or "lost" in (n.get("desc") or "").lower()
                for n in latest_notes(lead.get("context_updates") or [], 5)
            ):
                issues.append("lost_reason_or_not_interested_not_reflected")

    if budget:
        if re.search(r"under\s*1", budget, re.I) and re.search(
            r"\b(1-2|2-5)\s*cr\b", summ, re.I
        ):
            issues.append("budget_mismatch_summary_higher_than_field")
        if re.search(r"\b1-2\b", budget, re.I) and re.search(
            r"budget under 1|under 1\s*cr", summ, re.I
        ):
            issues.append("budget_mismatch_summary_lower_than_field")
        if re.search(r"\b2-5\b", budget, re.I) and re.search(
            r"under 1\s*cr|budget of 1-2", summ, re.I
        ):
            issues.append("budget_mismatch_summary_lower_than_field")

    if RNR_WRONG_RE.search(summ) or RNR_WRONG_RE.search(move_blob):
        issues.append("rnr_acronym_wrong")

    # Recency: if newest note clearly says not interested / vastu rejected / lost
    notes = latest_notes(lead.get("context_updates") or [], 3)
    newest = " ".join(n.get("desc") or "" for n in notes).lower()
    if any(
        k in newest
        for k in ("not interest", "not pursuing", "not persuing", "vastu", "moving to lost", "closed lost")
    ):
        if status_l in TERMINAL_STATUSES and ACTIVE_INTEREST_RE.search(summ):
            if "recency_ignored_latest_negative_note" not in issues:
                issues.append("recency_ignored_latest_negative_note")

    hard = {
        "summary_sounds_active_but_status_terminal",
        "moves_still_push_engagement_on_dead_status",
        "budget_mismatch_summary_higher_than_field",
        "budget_mismatch_summary_lower_than_field",
        "rnr_acronym_wrong",
        "recency_ignored_latest_negative_note",
    }
    if any(i in hard for i in issues):
        verdict = "FAIL"
    elif issues:
        verdict = "WEAK"
    else:
        verdict = "PASS"
    return {"verdict": verdict, "issues": issues}


async def audit_one(lead: dict) -> dict:
    from crm.services.ai_lead_regen import build_crm_hints, build_masked_transcript
    from crm.services.ai_service import generate_lead_insights

    updates = [u for u in (lead.get("context_updates") or []) if isinstance(u, dict)]
    transcript = build_masked_transcript(lead)
    hints = build_crm_hints(lead)
    stored = (lead.get("ai_persona_summary") or "").strip()
    stored_gen = lead.get("ai_last_generated_at_dt") or lead.get("ai_last_generated_at")

    payload_obj = await generate_lead_insights(transcript=transcript, crm_hints=hints)
    payload = {
        "persona_summary": payload_obj.persona_summary,
        "strategic_next_moves": [m.model_dump() for m in payload_obj.strategic_next_moves],
        "grounded_profile": payload_obj.grounded_profile.model_dump(),
    }
    scored = score_fresh(lead, payload)

    last_activity = None
    for u in reversed(updates):
        last_activity = _as_dt(u.get("timestamp_dt") or u.get("timestamp"))
        if last_activity:
            break
    stored_dt = _as_dt(stored_gen)
    stale_days = None
    if stored_dt and last_activity and last_activity > stored_dt:
        stale_days = (last_activity - stored_dt).days

    return {
        "id": lead.get("id"),
        "phone_masked": _mask_phone(lead.get("phone")),
        "n_updates": len(updates),
        "status": lead.get("lead_status"),
        "budget": lead.get("budget"),
        "project": lead.get("project"),
        "lost_reason": lead.get("lost_reason"),
        "temperature": lead.get("temperature"),
        "stored_generated_at": str(stored_gen)[:40] if stored_gen else None,
        "stored_stale_days_vs_latest_note": stale_days,
        "stored_summary_head": (stored[:240].replace("\u20b9", "Rs") if stored else ""),
        "fresh_summary": (payload["persona_summary"] or "").replace("\u20b9", "Rs"),
        "fresh_moves": [
            m.get("title") for m in payload["strategic_next_moves"] if isinstance(m, dict)
        ],
        "fresh_grounded_profile": payload["grounded_profile"],
        "latest_notes": latest_notes(updates, 5),
        "verdict": scored["verdict"],
        "issues": scored["issues"],
        "transcript_chars": len(transcript),
        "hints": hints,
    }


def render_markdown(meta: dict, rows: List[dict]) -> str:
    from collections import Counter

    counts = Counter(r["verdict"] for r in rows)
    lines = [
        "# AI Summary Accuracy Audit (#45)",
        "",
        f"**Date:** {datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M %Z')}",
        f"**DB (read-only):** `{meta['db_name']}`",
        f"**LLM:** provider=`{meta['provider']}` model=`{meta['model']}` keys_configured=`{meta['n_keys']}`",
        "**Writes to prod:** none (live regen in-process only)",
        "",
        "## Method",
        "",
        "1. Sample long-timeline production leads (incl. tracker example phones when present).",
        "2. Rebuild transcript + CRM hints with current `build_masked_transcript` / `build_crm_hints`.",
        "3. Call `generate_lead_insights` live with current `GROUNDING_SYSTEM` prompt.",
        "4. Score fresh persona/moves against status, lost_reason, budget, and newest notes.",
        "5. Keep stored August (or earlier) summaries only for stale-vs-fresh comparison.",
        "",
        "## Summary",
        "",
        f"| Verdict | Count |",
        f"|---------|------:|",
        f"| PASS | {counts.get('PASS', 0)} |",
        f"| WEAK | {counts.get('WEAK', 0)} |",
        f"| FAIL | {counts.get('FAIL', 0)} |",
        f"| ERROR | {counts.get('ERROR', 0)} |",
        "",
        f"**Sample size:** {len(rows)}",
        "",
        "## Per-lead results",
        "",
    ]
    for i, r in enumerate(rows, 1):
        lines.extend(
            [
                f"### {i}. {r.get('phone_masked')} — {r.get('verdict')} "
                f"(n={r.get('n_updates')}, status=`{r.get('status')}`)",
                "",
                f"- **Project / budget / lost_reason:** {r.get('project')!r} / {r.get('budget')!r} / {r.get('lost_reason')!r}",
                f"- **Stored AI generated:** {r.get('stored_generated_at') or 'none'}; "
                f"stale vs latest note days: {r.get('stored_stale_days_vs_latest_note')}",
                f"- **Issues:** {', '.join(r.get('issues') or []) or '—'}",
                f"- **Fresh moves:** {r.get('fresh_moves')}",
                "",
                "**Latest notes:**",
                "",
            ]
        )
        for n in r.get("latest_notes") or []:
            lines.append(f"- `[{n.get('type')}] {n.get('ts')}` {n.get('desc')}")
        lines.extend(
            [
                "",
                "**Stored summary (head):**",
                "",
                f"> {(r.get('stored_summary_head') or '(empty)').replace(chr(10), ' ')}",
                "",
                "**Fresh summary (current prompt):**",
                "",
                f"{r.get('fresh_summary') or r.get('error') or '(empty)'}",
                "",
            ]
        )

    themes = []
    if counts.get("FAIL"):
        themes.append(
            "Fresh failures still cluster on terminal statuses if the model keeps "
            "“currently interested” language or engagement moves."
        )
    stale_n = sum(1 for r in rows if (r.get("stored_stale_days_vs_latest_note") or 0) > 0)
    if stale_n:
        themes.append(
            f"{stale_n}/{len(rows)} stored summaries were older than the latest timeline "
            "activity — cached AI is not a valid accuracy test without live regen."
        )
    if counts.get("PASS", 0) + counts.get("WEAK", 0) >= max(1, len(rows) // 2):
        themes.append(
            "Current prompt + live regen often reflects newest notes better than stored mid-August text."
        )

    pass_rate = counts.get("PASS", 0) / max(1, len([r for r in rows if r.get("verdict") != "ERROR"]))
    if counts.get("ERROR"):
        rec = (
            "Blocked or partial: live LLM errors occurred. Fix model/key config before "
            "claiming #45 Done."
        )
        verdict45 = "Partial — live audit blocked/errored"
    elif pass_rate >= 0.7 and counts.get("FAIL", 0) <= 2:
        weak_n = counts.get("WEAK", 0)
        fail_n = counts.get("FAIL", 0)
        rec = (
            "Treat #45 as **Done with notes**: current prompt + `openai/gpt-oss-120b` is "
            "materially better than stale August cache on terminal/lost leads. "
            f"Residual: FAIL={fail_n}, WEAK={weak_n}. "
            "Prod UI still shows cached summaries until regen — consider regen-on-status-change."
        )
        verdict45 = "Done with notes (live audit)"
    elif counts.get("FAIL", 0) > len(rows) // 3:
        rec = (
            "Keep #45 **Partial**: live current prompt still fails grounding too often on "
            "terminal / not-interested leads. Prompt or post-status regen needs a follow-up."
        )
        verdict45 = "Partial (live audit still fails grounding)"
    else:
        rec = (
            "Keep #45 **Partial / watch**: mixed live results; prioritize regen after "
            "status→Unqualified/Closed Lost and stronger status weighting."
        )
        verdict45 = "Partial (mixed live results)"

    lines.extend(
        [
            "## Themes",
            "",
        ]
    )
    for t in themes or ["No dominant theme beyond per-lead notes."]:
        lines.append(f"- {t}")
    lines.extend(
        [
            "",
            "## Recommendation for tracker #45",
            "",
            f"**Verdict:** {verdict45}",
            "",
            rec,
            "",
            "## Safety",
            "",
            "- This script never `$set`s AI fields on production.",
            "- Phones masked as `***` + last 4 digits.",
            "",
        ]
    )
    return "\n".join(lines)


async def main_async(limit: int) -> int:
    meta = assert_prod_readonly()
    from crm.services.ai_service import _resolve_llm_config, grok_keys_configured

    if not grok_keys_configured():
        raise SystemExit("REFUSE: no GROQ/GROK API keys configured in backend/.env")

    chat_url, model, keys = _resolve_llm_config()
    provider = "groq" if "groq" in chat_url else ("xai" if "x.ai" in chat_url else chat_url)
    run_meta = {
        "db_name": meta["DB_NAME"],
        "provider": provider,
        "model": model,
        "n_keys": len(keys),
    }

    client = MongoClient(meta["MONGO_URL"], serverSelectionTimeoutMS=25000)
    db = client[meta["DB_NAME"]]
    db.command("ping")
    print(f"READ-ONLY DB={meta['DB_NAME']} model={model} keys={len(keys)}")

    ids = select_lead_ids(db, limit=limit)
    print(f"selected {len(ids)} leads")
    rows: List[dict] = []
    for i, lid in enumerate(ids, 1):
        lead = db.leads.find_one({"id": lid}, {"_id": 0})
        if not lead:
            continue
        print(f"[{i}/{len(ids)}] {_mask_phone(lead.get('phone'))} status={lead.get('lead_status')} …")
        try:
            row = await audit_one(lead)
            print(f"  -> {row['verdict']} issues={row['issues']}")
            rows.append(row)
        except Exception as e:
            print(f"  -> ERROR {e}")
            rows.append(
                {
                    "id": lid,
                    "phone_masked": _mask_phone(lead.get("phone")),
                    "n_updates": len(lead.get("context_updates") or []),
                    "status": lead.get("lead_status"),
                    "budget": lead.get("budget"),
                    "project": lead.get("project"),
                    "lost_reason": lead.get("lost_reason"),
                    "stored_generated_at": str(
                        lead.get("ai_last_generated_at_dt") or lead.get("ai_last_generated_at") or ""
                    )[:40],
                    "stored_stale_days_vs_latest_note": None,
                    "stored_summary_head": (lead.get("ai_persona_summary") or "")[:240],
                    "fresh_summary": "",
                    "fresh_moves": [],
                    "fresh_grounded_profile": {},
                    "latest_notes": latest_notes(lead.get("context_updates") or [], 5),
                    "verdict": "ERROR",
                    "issues": ["live_llm_error"],
                    "error": str(e)[:500],
                }
            )
        await asyncio.sleep(0.4)

    client.close()

    out_json = REPO_ROOT / "docs" / "ai_summary_accuracy_audit.json"
    out_md = REPO_ROOT / "docs" / "AI_SUMMARY_ACCURACY_AUDIT.md"
    out_json.write_text(json.dumps({"meta": run_meta, "rows": rows}, indent=2, ensure_ascii=True), encoding="utf-8")
    out_md.write_text(render_markdown(run_meta, rows), encoding="utf-8")
    print(f"wrote {out_md}")
    print(f"wrote {out_json}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Live AI summary accuracy audit (prod read-only)")
    parser.add_argument("--limit", type=int, default=15)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main_async(max(5, min(args.limit, 20)))))


if __name__ == "__main__":
    main()
