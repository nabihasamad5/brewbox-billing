from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from brewbox.models import PausePeriod, SubscriptionStatus


def _status(service, sub, day):
    return service.repo.subscriptions[sub["id"]].status_on(day)


# ---------------------------------------------------------------- validation
def test_seven_day_pause_is_accepted(service, starter_sub):
    pause = service.pause_subscription(starter_sub["id"], date(2025, 3, 10), date(2025, 3, 16))

    assert pause == PausePeriod(date(2025, 3, 10), date(2025, 3, 16))
    assert pause.days == 7


def test_six_day_pause_is_rejected(service, starter_sub):
    with pytest.raises(ValueError):
        service.pause_subscription(starter_sub["id"], date(2025, 3, 10), date(2025, 3, 15))
    assert service.list_pauses(starter_sub["id"]) == []


def test_ninety_day_pause_is_accepted(service, starter_sub):
    pause = service.pause_subscription(starter_sub["id"], date(2025, 3, 10), date(2025, 6, 7))

    assert pause.days == 90


def test_ninety_one_day_pause_is_rejected(service, starter_sub):
    with pytest.raises(ValueError):
        service.pause_subscription(starter_sub["id"], date(2025, 3, 10), date(2025, 6, 8))


def test_start_after_end_is_rejected(service, starter_sub):
    with pytest.raises(ValueError):
        service.pause_subscription(starter_sub["id"], date(2025, 3, 20), date(2025, 3, 10))


def test_pause_cannot_start_before_subscription_start(service, starter_sub):
    with pytest.raises(ValueError):
        service.pause_subscription(starter_sub["id"], date(2024, 12, 25), date(2025, 1, 5))


def test_pause_may_start_on_subscription_start_date(service, starter_sub):
    pause = service.pause_subscription(starter_sub["id"], date(2025, 1, 1), date(2025, 1, 7))

    assert pause.days == 7


def test_unknown_subscription_is_rejected(service):
    with pytest.raises(ValueError):
        service.pause_subscription("sub-9999", date(2025, 3, 10), date(2025, 3, 16))


def test_cancelled_subscription_cannot_be_paused(service, starter_sub):
    service.repo.subscriptions[starter_sub["id"]].cancelled_on = date(2025, 2, 1)

    with pytest.raises(ValueError):
        service.pause_subscription(starter_sub["id"], date(2025, 3, 10), date(2025, 3, 16))


def test_overlapping_pauses_are_rejected_but_adjacent_ones_are_not(service, starter_sub):
    sid = starter_sub["id"]
    service.pause_subscription(sid, date(2025, 3, 10), date(2025, 3, 16))

    with pytest.raises(ValueError):  # shares 16 March
        service.pause_subscription(sid, date(2025, 3, 16), date(2025, 3, 22))
    with pytest.raises(ValueError):  # fully contained
        service.pause_subscription(sid, date(2025, 3, 11), date(2025, 3, 17))
    with pytest.raises(ValueError):  # fully contains the first
        service.pause_subscription(sid, date(2025, 3, 1), date(2025, 3, 31))

    service.pause_subscription(sid, date(2025, 3, 17), date(2025, 3, 23))  # adjacent: ok
    assert len(service.list_pauses(sid)) == 2


# ----------------------------------------------------------- overdue guardrail
def _overdue_setup(service, starter_sub):
    # January invoice issued 1 Jan, due 15 Jan, left unpaid.
    return service.issue_invoice(starter_sub["id"], 2025, 1, issued_on=date(2025, 1, 1))


def test_overdue_invoice_blocks_pause(service, starter_sub):
    _overdue_setup(service, starter_sub)  # today is 1 March: overdue

    with pytest.raises(ValueError):
        service.pause_subscription(starter_sub["id"], date(2025, 3, 10), date(2025, 3, 16))


def test_overdue_boundary_due_date_itself_is_not_overdue(service, starter_sub):
    _overdue_setup(service, starter_sub)
    sid = starter_sub["id"]

    # On the due date the invoice is not yet overdue ...
    service.pause_subscription(sid, date(2025, 3, 10), date(2025, 3, 16), as_of=date(2025, 1, 15))

    # ... the day after, it is.
    with pytest.raises(ValueError):
        service.pause_subscription(sid, date(2025, 4, 10), date(2025, 4, 16), as_of=date(2025, 1, 16))


def test_overdue_check_uses_today_not_the_future_pause_start(service, starter_sub):
    _overdue_setup(service, starter_sub)

    with pytest.raises(ValueError):
        service.pause_subscription(starter_sub["id"], date(2025, 9, 1), date(2025, 9, 14))


def test_partially_paid_overdue_invoice_still_blocks(service, starter_sub):
    invoice = _overdue_setup(service, starter_sub)
    service.record_payment(invoice.id, amount="5.00", paid_on=date(2025, 1, 10))

    with pytest.raises(ValueError):
        service.pause_subscription(starter_sub["id"], date(2025, 3, 10), date(2025, 3, 16))


def test_settled_invoice_no_longer_blocks_pause(service, starter_sub):
    invoice = _overdue_setup(service, starter_sub)
    service.record_payment(invoice.id, paid_on=date(2025, 2, 1))

    pause = service.pause_subscription(starter_sub["id"], date(2025, 3, 10), date(2025, 3, 16))

    assert pause.days == 7


def test_unpaid_invoice_that_is_not_yet_due_does_not_block(service, starter_sub):
    service.issue_invoice(starter_sub["id"], 2025, 3, issued_on=date(2025, 3, 1))

    pause = service.pause_subscription(starter_sub["id"], date(2025, 4, 1), date(2025, 4, 7))

    assert pause.days == 7


# ------------------------------------------------------------------- billing
def test_inclusive_dates_10_to_19_january_resume_on_the_20th(service, starter_sub):
    sid = starter_sub["id"]
    pause = service.pause_subscription(sid, date(2025, 1, 10), date(2025, 1, 19), as_of=date(2025, 1, 5))

    assert pause.days == 10
    assert _status(service, starter_sub, date(2025, 1, 9)) == SubscriptionStatus.ACTIVE
    assert _status(service, starter_sub, date(2025, 1, 10)) == SubscriptionStatus.PAUSED
    assert _status(service, starter_sub, date(2025, 1, 19)) == SubscriptionStatus.PAUSED
    assert _status(service, starter_sub, date(2025, 1, 20)) == SubscriptionStatus.ACTIVE

    invoice = service.issue_invoice(sid, 2025, 1, issued_on=date(2025, 1, 1))
    # 21 of 31 days: 18.00 -> 12.19 ; 7.00 -> 4.74 ; tax on 16.93 = 1.40
    assert invoice.subtotal == Decimal("16.93")
    assert invoice.tax_total == Decimal("1.40")
    assert invoice.total == Decimal("18.33")


def test_paused_days_are_removed_from_plan_and_every_addon(service, ana):
    sub = service.create_subscription(
        ana["id"], "starter", ["extra_bag", "grinder"], start_date=date(2025, 1, 1)
    )
    service.pause_subscription(sub["id"], date(2025, 1, 10), date(2025, 1, 19), as_of=date(2025, 1, 5))

    invoice = service.issue_invoice(sub["id"], 2025, 1, issued_on=date(2025, 1, 1))

    amounts = [l.amount for l in invoice.lines[:3]]
    # 21/31 of 18.00, 7.00 and 5.00
    assert amounts == [Decimal("12.19"), Decimal("4.74"), Decimal("3.39")]


def test_fully_paused_month_produces_no_invoice(service, starter_sub):
    sid = starter_sub["id"]
    service.pause_subscription(sid, date(2025, 2, 1), date(2025, 2, 28))

    assert service.issue_invoice(sid, 2025, 2, issued_on=date(2025, 2, 1)) is None
    assert service.repo.invoices == {}


def test_month_after_a_full_month_pause_is_prorated_for_the_spill_over(service, starter_sub):
    sid = starter_sub["id"]
    service.pause_subscription(sid, date(2025, 2, 1), date(2025, 3, 2))  # 30 days

    assert service.issue_invoice(sid, 2025, 2, issued_on=date(2025, 2, 1)) is None
    invoice = service.issue_invoice(sid, 2025, 3, issued_on=date(2025, 3, 3))

    # 29 of 31 days: 18.00 -> 16.84 ; 7.00 -> 6.55 ; tax on 23.39 = 1.93
    assert invoice.subtotal == Decimal("23.39")
    assert invoice.tax_total == Decimal("1.93")
    assert invoice.total == Decimal("25.32")


def test_pause_crossing_month_boundary_prorates_both_months(service, starter_sub):
    sid = starter_sub["id"]
    service.pause_subscription(sid, date(2025, 1, 28), date(2025, 2, 6), as_of=date(2025, 1, 5))

    jan = service.issue_invoice(sid, 2025, 1, issued_on=date(2025, 1, 1))
    feb = service.issue_invoice(sid, 2025, 2, issued_on=date(2025, 2, 1))

    # January loses 4 days (28-31): 27/31. 15.68 + 6.10 = 21.78, tax 1.80
    assert jan.subtotal == Decimal("21.78")
    assert jan.total == Decimal("23.58")
    # February loses 6 days (1-6): 22/28. 14.14 + 5.50 = 19.64, tax 1.62
    assert feb.subtotal == Decimal("19.64")
    assert feb.total == Decimal("21.26")


def test_mid_month_start_combined_with_pause(service, ana):
    sub = service.create_subscription(
        ana["id"], "starter", ["extra_bag"], start_date=date(2025, 3, 15)
    )
    service.pause_subscription(sub["id"], date(2025, 3, 20), date(2025, 3, 26))

    invoice = service.issue_invoice(sub["id"], 2025, 3, issued_on=date(2025, 3, 15))

    # 17 days from the start minus 7 paused = 10 of 31: 5.81 + 2.26 = 8.07, tax 0.67
    assert invoice.subtotal == Decimal("8.07")
    assert invoice.total == Decimal("8.74")


def test_existing_invoice_is_not_recalculated_by_a_later_pause(service, starter_sub):
    sid = starter_sub["id"]
    invoice = service.issue_invoice(sid, 2025, 1, issued_on=date(2025, 1, 1))
    total_before = invoice.total

    service.pause_subscription(sid, date(2025, 1, 10), date(2025, 1, 19), as_of=date(2025, 1, 5))
    again = service.issue_invoice(sid, 2025, 1, issued_on=date(2025, 1, 2))

    assert again is invoice
    assert invoice.total == total_before == Decimal("27.06")
    assert invoice.credit_applied == Decimal("0.00")


def test_pause_blocks_billing_only_inside_the_window(service, starter_sub):
    sid = starter_sub["id"]
    service.pause_subscription(sid, date(2025, 3, 10), date(2025, 3, 16))

    jan = service.issue_invoice(sid, 2025, 1, issued_on=date(2025, 1, 1))

    assert jan.total == Decimal("27.06")


# -------------------------------------------------------------------- resume
def test_early_resume_shortens_pause_and_resume_day_is_active(service, starter_sub):
    sid = starter_sub["id"]
    service.pause_subscription(sid, date(2025, 3, 10), date(2025, 3, 30))

    resumed = service.resume_subscription(sid, date(2025, 3, 20))

    assert resumed == PausePeriod(date(2025, 3, 10), date(2025, 3, 19))
    assert service.list_pauses(sid) == [resumed]
    assert _status(service, starter_sub, date(2025, 3, 19)) == SubscriptionStatus.PAUSED
    assert _status(service, starter_sub, date(2025, 3, 20)) == SubscriptionStatus.ACTIVE

    invoice = service.issue_invoice(sid, 2025, 3, issued_on=date(2025, 3, 1))
    # 10 paused days -> 21 of 31, same maths as the January example
    assert invoice.total == Decimal("18.33")


def test_early_resume_must_leave_at_least_seven_paused_days(service, starter_sub):
    sid = starter_sub["id"]
    service.pause_subscription(sid, date(2025, 3, 10), date(2025, 3, 30))

    with pytest.raises(ValueError):  # would leave 10-15 = 6 days
        service.resume_subscription(sid, date(2025, 3, 16))
    assert service.list_pauses(sid)[0].end == date(2025, 3, 30)  # unchanged

    resumed = service.resume_subscription(sid, date(2025, 3, 17))  # leaves exactly 7
    assert resumed.days == 7


def test_resume_on_the_first_pause_day_is_rejected(service, starter_sub):
    sid = starter_sub["id"]
    service.pause_subscription(sid, date(2025, 3, 10), date(2025, 3, 30))

    with pytest.raises(ValueError):
        service.resume_subscription(sid, date(2025, 3, 10))


def test_resume_without_an_active_pause_is_rejected(service, starter_sub):
    sid = starter_sub["id"]
    with pytest.raises(ValueError):
        service.resume_subscription(sid, date(2025, 3, 20))

    service.pause_subscription(sid, date(2025, 3, 10), date(2025, 3, 16))
    with pytest.raises(ValueError):  # pause already over on 20 March
        service.resume_subscription(sid, date(2025, 3, 20))


def test_resume_only_touches_the_pause_containing_that_date(service, starter_sub):
    sid = starter_sub["id"]
    service.pause_subscription(sid, date(2025, 3, 1), date(2025, 3, 10))
    service.pause_subscription(sid, date(2025, 4, 1), date(2025, 4, 30))

    service.resume_subscription(sid, date(2025, 4, 20))

    assert service.list_pauses(sid) == [
        PausePeriod(date(2025, 3, 1), date(2025, 3, 10)),
        PausePeriod(date(2025, 4, 1), date(2025, 4, 19)),
    ]


# --------------------------------------------------------------------- audit
def test_list_pauses_is_sorted_and_returns_a_copy(service, starter_sub):
    sid = starter_sub["id"]
    service.pause_subscription(sid, date(2025, 5, 1), date(2025, 5, 7))
    service.pause_subscription(sid, date(2025, 3, 1), date(2025, 3, 7))

    pauses = service.list_pauses(sid)

    assert [p.start for p in pauses] == [date(2025, 3, 1), date(2025, 5, 1)]
    pauses.clear()
    assert len(service.list_pauses(sid)) == 2


def test_list_pauses_unknown_subscription(service):
    with pytest.raises(ValueError):
        service.list_pauses("sub-9999")
