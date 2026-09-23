# Client message — Escalation Queue auto-resolve (copy/paste)

**Subject:** Quick decision — Escalation Queue auto-resolve

Hi team,

We investigated the Reserve 16 lead (Ambikapathy / 919884988828) showing on Escalation Queue despite a follow-up task scheduled for 24 Sep.

**What happened:** The escalation was triggered on 14 Sep at 12:20 PM — the **New lead 2-hour admin alert**, before jigar contacted the client. jigar later moved the lead to Contacted and scheduled a site-visit call for 24 Sep. The escalation row stayed open because the system does not currently auto-close escalations when a rep schedules a future follow-up.

**Proposed improvement:** Auto-dismiss (resolve) open escalation notifications when either:

1. The lead moves out of **New** status (e.g. to Contacted, RNR, etc.) after rep action, or
2. The rep schedules a **future-dated follow-up task** on that lead

**Benefits:** Escalation Queue shows only leads that still need admin attention; fewer false alarms like this one.

**Question:** Should we implement this auto-dismiss behaviour? If yes, we'll add it in a separate small release after the SLA task-stacking fix.

Thanks
