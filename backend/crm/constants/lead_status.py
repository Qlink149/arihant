"""Shared SLA-aligned lead status labels and closed-status matching."""

UI_LEAD_STATUSES = [
    "New",
    "RNR",
    "Contacted",
    "Nurturing",
    "Site Visit Scheduled",
    "Visit Completed",
    "Negotiation",
    "Gone Cold",
    "Future Prospect",
    "Closed Won",
    "Closed Lost",
]

# Regex for dashboard closed-lead counts (aligns with SLA + legacy labels)
CLOSED_LEAD_STATUS_REGEX = (
    r"advance paid|closed won|closed lost|closed|booked|won|lost"
)

NURTURING_STATUS = "Nurturing"
NURTURE_LABELS = ("Hot", "Warm")
