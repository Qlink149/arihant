"""
test_brevo.py — Brevo email integration tester for Arihant CRM
================================================================
Sends a realistic test email for every alert template the app uses.

Usage (from the backend/ directory):
    python scripts/test_brevo.py
"""

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 output so Unicode characters work in all Windows terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ── resolve project root so we can load .env without running the full app ──
BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_ROOT / ".env")
except ImportError:
    print("⚠  python-dotenv not installed – reading env vars only from shell environment")

try:
    import httpx
except ImportError:
    print("❌  httpx not installed. Run:  pip install httpx")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────
# Configuration (read from .env / environment)
# ─────────────────────────────────────────────────────────────
API_KEY        = os.environ.get("BREVO_API_KEY", "")
ALERT_EMAIL    = os.environ.get("BREVO_ALERT_EMAIL", "")
SENDER_EMAIL   = os.environ.get("BREVO_SENDER_EMAIL", "")
SENDER_NAME    = os.environ.get("BREVO_SENDER_NAME", "Arihant CRM")
DASHBOARD_URL  = os.environ.get("DASHBOARD_URL", "http://localhost:3000")

BREVO_ENDPOINT = "https://api.brevo.com/v3/smtp/email"

# ─────────────────────────────────────────────────────────────
# Shared HTML helpers
# ─────────────────────────────────────────────────────────────

BASE_STYLE = """
<style>
  body { font-family: 'Segoe UI', Arial, sans-serif; background:#f4f6f9; margin:0; padding:0; }
  .wrapper { max-width:640px; margin:40px auto; background:#fff;
             border-radius:12px; overflow:hidden;
             box-shadow:0 4px 24px rgba(0,0,0,.08); }
  .header  { background:linear-gradient(135deg,#1a1f36 0%,#2d3561 100%);
             padding:32px 36px; }
  .header h1 { color:#fff; margin:0; font-size:22px; font-weight:700; }
  .header p  { color:#a0a8c8; margin:6px 0 0; font-size:13px; }
  .body    { padding:32px 36px; color:#333; }
  .stat    { background:#f0f4ff; border-left:4px solid #4361ee;
             border-radius:6px; padding:16px 20px; margin:16px 0; }
  .stat .num  { font-size:36px; font-weight:800; color:#4361ee; }
  .stat .label{ font-size:13px; color:#666; margin-top:2px; }
  table   { width:100%; border-collapse:collapse; margin:20px 0; font-size:13px; }
  th      { background:#f0f4ff; color:#4361ee; padding:10px 12px;
            text-align:left; border-bottom:2px solid #d8e0ff; }
  td      { padding:10px 12px; border-bottom:1px solid #eee; color:#444; }
  tr:last-child td { border-bottom:none; }
  .badge  { display:inline-block; padding:3px 10px; border-radius:20px;
            font-size:11px; font-weight:600; }
  .badge-high   { background:#ffe0e0; color:#c0392b; }
  .badge-medium { background:#fff3cd; color:#856404; }
  .badge-low    { background:#d4edda; color:#155724; }
  .cta    { text-align:center; margin:28px 0 8px; }
  .btn    { display:inline-block; background:#4361ee; color:#fff !important;
            padding:13px 32px; border-radius:8px; text-decoration:none;
            font-weight:600; font-size:14px; }
  .footer { background:#f8f9fc; padding:20px 36px; text-align:center;
            font-size:11px; color:#aaa; border-top:1px solid #eee; }
</style>
"""


def _wrap(header_title: str, header_sub: str, body_html: str) -> str:
    now_str = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
{BASE_STYLE}
</head>
<body>
<div class="wrapper">
  <div class="header">
    <h1>🏢 Arihant CRM — {header_title}</h1>
    <p>{header_sub} &nbsp;·&nbsp; {now_str}</p>
  </div>
  <div class="body">
    {body_html}
  </div>
  <div class="footer">
    Arihant CRM &nbsp;|&nbsp; This is an automated internal alert.<br>
    <a href="{DASHBOARD_URL}" style="color:#4361ee;">Open Dashboard</a>
  </div>
</div>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────
# Template builders  (mirror the real app templates)
# ─────────────────────────────────────────────────────────────

def build_nurturing_review_html(lead_count: int, lead_rows: list) -> str:
    rows_html = ""
    for r in lead_rows[:20]:
        severity = "high" if r["days"] >= 21 else ("medium" if r["days"] >= 14 else "low")
        rows_html += (
            f"<tr><td>{r['name']}</td>"
            f"<td>{r['status']}</td>"
            f"<td><span class='badge badge-{severity}'>{r['days']} days</span></td></tr>"
        )
    body = f"""
    <p>Hi Admin,</p>
    <p>The following leads have been stuck in <strong>Nurturing</strong> for <strong>14+ days</strong>
       without a booking-progress update. Immediate review is recommended.</p>
    <div class="stat">
      <div class="num">{lead_count}</div>
      <div class="label">Leads requiring review</div>
    </div>
    <table>
      <thead><tr><th>Lead Name</th><th>Status</th><th>Days in Nurturing</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
    <div class="cta">
      <a class="btn" href="{DASHBOARD_URL}/leads?filter=nurturing">Review Leads →</a>
    </div>
    <p style="color:#888;font-size:12px;margin-top:24px;">
      This report is generated automatically each day at 9 AM. 
      Leads already progressed to a booking status are excluded.
    </p>"""
    return _wrap(
        "Nurturing Review Alert",
        f"{lead_count} leads stuck in Nurturing — 14+ days",
        body,
    )


def build_rnr_followup_html(leads: list) -> str:
    rows_html = ""
    for r in leads[:20]:
        rows_html += (
            f"<tr><td>{r['name']}</td>"
            f"<td>{r.get('assigned_to','—')}</td>"
            f"<td><span class='badge badge-high'>{r['hours_ago']}h ago</span></td></tr>"
        )
    count = len(leads)
    body = f"""
    <p>Hi Admin,</p>
    <p>The following <strong>RNR (Ring No Response)</strong> leads have not been followed up 
       within the 24-hour SLA window.</p>
    <div class="stat">
      <div class="num">{count}</div>
      <div class="label">RNR leads overdue for follow-up</div>
    </div>
    <table>
      <thead><tr><th>Lead Name</th><th>Assigned To</th><th>Last Attempt</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
    <div class="cta">
      <a class="btn" href="{DASHBOARD_URL}/leads?filter=rnr">View RNR Leads →</a>
    </div>"""
    return _wrap(
        "RNR Follow-up Alert",
        f"{count} RNR leads overdue",
        body,
    )


def build_dormant_lead_html(leads: list) -> str:
    rows_html = ""
    for r in leads[:20]:
        rows_html += (
            f"<tr><td>{r['name']}</td>"
            f"<td>{r.get('status','—')}</td>"
            f"<td><span class='badge badge-medium'>{r['days_ago']} days</span></td></tr>"
        )
    count = len(leads)
    body = f"""
    <p>Hi Admin,</p>
    <p>The following leads have had <strong>no activity for 7+ days</strong> and are at risk 
       of going cold.</p>
    <div class="stat">
      <div class="num">{count}</div>
      <div class="label">Dormant leads</div>
    </div>
    <table>
      <thead><tr><th>Lead Name</th><th>Status</th><th>Inactive For</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
    <div class="cta">
      <a class="btn" href="{DASHBOARD_URL}/leads?filter=dormant">Review Dormant Leads →</a>
    </div>"""
    return _wrap(
        "Dormant Lead Alert",
        f"{count} dormant leads",
        body,
    )


def build_task_overdue_html(tasks: list) -> str:
    rows_html = ""
    for t in tasks[:20]:
        rows_html += (
            f"<tr><td>{t['description']}</td>"
            f"<td>{t.get('assigned_to','—')}</td>"
            f"<td><span class='badge badge-high'>{t['due_date']}</span></td></tr>"
        )
    count = len(tasks)
    body = f"""
    <p>Hi Admin,</p>
    <p>The following tasks are <strong>overdue</strong> and require immediate attention.</p>
    <div class="stat">
      <div class="num">{count}</div>
      <div class="label">Overdue tasks</div>
    </div>
    <table>
      <thead><tr><th>Task</th><th>Assigned To</th><th>Due Date</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
    <div class="cta">
      <a class="btn" href="{DASHBOARD_URL}/tasks">View Tasks →</a>
    </div>"""
    return _wrap(
        "Overdue Tasks Alert",
        f"{count} tasks overdue",
        body,
    )


# ─────────────────────────────────────────────────────────────
# HTTP sender
# ─────────────────────────────────────────────────────────────

async def send_email(subject: str, html_content: str, label: str) -> bool:
    payload = {
        "sender":      {"name": SENDER_NAME, "email": SENDER_EMAIL},
        "to":          [{"email": ALERT_EMAIL}],
        "subject":     f"[TEST] {subject}",
        "htmlContent": html_content,
    }
    headers = {
        "api-key":      API_KEY,
        "Content-Type": "application/json",
        "Accept":       "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(BREVO_ENDPOINT, headers=headers, json=payload)
        if resp.status_code in (200, 201):
            data = resp.json()
            msg_id = data.get("messageId", "—")
            print(f"  ✅  {label}  →  sent  (messageId: {msg_id})")
            return True
        else:
            print(f"  ❌  {label}  →  HTTP {resp.status_code}: {resp.text[:300]}")
            return False
    except Exception as exc:
        print(f"  ❌  {label}  →  Exception: {exc}")
        return False


# ─────────────────────────────────────────────────────────────
# Main test runner
# ─────────────────────────────────────────────────────────────

async def run_tests():
    print("\n" + "═" * 60)
    print("  Arihant CRM — Brevo Email Integration Test")
    print("═" * 60)
    print(f"  API Key   : {API_KEY[:12]}…{API_KEY[-6:] if len(API_KEY) > 18 else '(short)'}")
    print(f"  From      : {SENDER_NAME} <{SENDER_EMAIL}>")
    print(f"  To        : {ALERT_EMAIL}")
    print(f"  Dashboard : {DASHBOARD_URL}")
    print("═" * 60 + "\n")

    if not API_KEY:
        print("❌  BREVO_API_KEY is not set. Check your .env file.")
        return
    if not ALERT_EMAIL:
        print("❌  BREVO_ALERT_EMAIL is not set. Check your .env file.")
        return
    if not SENDER_EMAIL:
        print("❌  BREVO_SENDER_EMAIL is not set. Check your .env file.")
        return

    results = []

    # ── 1. Nurturing Review Alert ──────────────────────────────
    print("📧  [1/4] Nurturing Review Alert")
    sample_leads_nurturing = [
        {"name": "Ramesh Kumar",   "status": "Nurturing", "days": 25},
        {"name": "Priya Sharma",   "status": "Nurturing", "days": 19},
        {"name": "Arjun Mehta",    "status": "Nurturing", "days": 15},
        {"name": "Sneha Iyer",     "status": "Nurturing", "days": 14},
        {"name": "Vikram Nair",    "status": "Nurturing", "days": 21},
    ]
    ok = await send_email(
        subject="5 leads stuck in Nurturing — 14+ days",
        html_content=build_nurturing_review_html(5, sample_leads_nurturing),
        label="nurturing_review_alert",
    )
    results.append(("Nurturing Review Alert", ok))

    # ── 2. RNR Follow-up Alert ─────────────────────────────────
    print("\n📧  [2/4] RNR Follow-up Alert")
    sample_rnr_leads = [
        {"name": "Kiran Patel",    "assigned_to": "Raj Singh",   "hours_ago": 36},
        {"name": "Meena Desai",    "assigned_to": "Pooja Verma", "hours_ago": 28},
        {"name": "Suresh Reddy",   "assigned_to": "Amit Joshi",  "hours_ago": 48},
    ]
    ok = await send_email(
        subject="3 RNR leads overdue for follow-up",
        html_content=build_rnr_followup_html(sample_rnr_leads),
        label="rnr_followup_alert",
    )
    results.append(("RNR Follow-up Alert", ok))

    # ── 3. Dormant Lead Alert ──────────────────────────────────
    print("\n📧  [3/4] Dormant Lead Alert")
    sample_dormant = [
        {"name": "Anita Kapoor",   "status": "Contacted",   "days_ago": 12},
        {"name": "Rohit Sharma",   "status": "Visit Completed", "days_ago": 9},
        {"name": "Divya Pillai",   "status": "Negotiation", "days_ago": 8},
    ]
    ok = await send_email(
        subject="3 dormant leads — no activity for 7+ days",
        html_content=build_dormant_lead_html(sample_dormant),
        label="dormant_lead_alert",
    )
    results.append(("Dormant Lead Alert", ok))

    # ── 4. Overdue Tasks Alert ─────────────────────────────────
    print("\n📧  [4/4] Overdue Tasks Alert")
    sample_tasks = [
        {"description": "Call back Ramesh Kumar re: site visit", "assigned_to": "Raj Singh",   "due_date": "2026-06-02"},
        {"description": "Send pricing proposal to Meena Desai",  "assigned_to": "Pooja Verma", "due_date": "2026-06-01"},
        {"description": "Follow-up with Kiran Patel after visit", "assigned_to": "Amit Joshi", "due_date": "2026-05-31"},
    ]
    ok = await send_email(
        subject="3 overdue tasks require attention",
        html_content=build_task_overdue_html(sample_tasks),
        label="task_overdue_alert",
    )
    results.append(("Overdue Tasks Alert", ok))

    # ── Summary ────────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("  Test Summary")
    print("═" * 60)
    passed = 0
    for name, ok in results:
        icon = "✅" if ok else "❌"
        print(f"  {icon}  {name}")
        if ok:
            passed += 1
    print("─" * 60)
    print(f"  {passed}/{len(results)} emails sent successfully to {ALERT_EMAIL}")
    print("═" * 60 + "\n")

    if passed == len(results):
        print("🎉  All tests passed! Check your inbox.\n")
    else:
        print("⚠   Some emails failed. Check your BREVO_API_KEY and sender domain verification.\n")


if __name__ == "__main__":
    asyncio.run(run_tests())
