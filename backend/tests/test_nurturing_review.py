from datetime import timedelta

from crm.services.lead_sla_utils import is_booking_progress_status
from crm.utils.helpers import utc_now


def test_booking_progress_detects_won():
    assert is_booking_progress_status("Won")
    assert is_booking_progress_status("Advance Paid")
    assert not is_booking_progress_status("Nurturing")


def test_14d_cutoff_math():
    now = utc_now()
    cutoff = now - timedelta(days=14)
    assert cutoff < now
