from crm.services.lead_sla_utils import is_booking_progress_status


def test_visit_7d_booking_progress_negotiation():
    assert is_booking_progress_status("Negotiation")


def test_visit_7d_not_booking_for_visit_completed_label():
    assert not is_booking_progress_status("Visit Completed")
