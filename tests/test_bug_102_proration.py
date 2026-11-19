from __future__ import annotations

from datetime import date
from decimal import Decimal

from brewbox.models import LineKind


def _sub(service, customer, start, discount=0, addons=("extra_bag",)):
    return service.create_subscription(
        customer["id"],
        plan_code="starter",
        addon_codes=addons,
        start_date=start,
        discount_percent=discount,
    )


def _amounts(invoice):
    plan = next(l for l in invoice.lines if l.kind == LineKind.PLAN).amount
    addon = next(l for l in invoice.lines if l.kind == LineKind.ADDON).amount
    return plan, addon


def test_march_15_start_bills_17_of_31_days_and_keeps_full_period(service, ana):
    sub = _sub(service, ana, date(2025, 3, 15))
    invoice = service.issue_invoice(sub["id"], 2025, 3, issued_on=date(2025, 3, 15))

    assert _amounts(invoice) == (Decimal("9.87"), Decimal("3.84"))
    assert invoice.subtotal == Decimal("13.71")
    assert invoice.tax_total == Decimal("1.13")
    assert invoice.total == Decimal("14.84")
    # The period describes the whole calendar month, not just the active days.
    assert invoice.period_start == date(2025, 3, 1)
    assert invoice.period_end == date(2025, 3, 31)


def test_full_month_is_billed_at_list_price_with_no_drift(service, ana):
    sub = _sub(service, ana, date(2024, 12, 20))
    invoice = service.issue_invoice(sub["id"], 2025, 1, issued_on=date(2025, 1, 1))

    assert _amounts(invoice) == (Decimal("18.00"), Decimal("7.00"))


def test_start_on_first_day_of_month_is_a_full_month(service, ana):
    sub = _sub(service, ana, date(2025, 3, 1))
    invoice = service.issue_invoice(sub["id"], 2025, 3, issued_on=date(2025, 3, 1))

    assert _amounts(invoice) == (Decimal("18.00"), Decimal("7.00"))


def test_last_day_of_month_bills_one_day(service, ana):
    sub = _sub(service, ana, date(2025, 3, 31))
    invoice = service.issue_invoice(sub["id"], 2025, 3, issued_on=date(2025, 3, 31))

    # 18.00 / 31 = 0.58 ; 7.00 / 31 = 0.23 ; tax on 0.81 = 0.07
    assert _amounts(invoice) == (Decimal("0.58"), Decimal("0.23"))
    assert invoice.tax_total == Decimal("0.07")
    assert invoice.total == Decimal("0.88")


def test_leap_february_uses_29_days(service, ana):
    sub = _sub(service, ana, date(2024, 2, 15))
    invoice = service.issue_invoice(sub["id"], 2024, 2, issued_on=date(2024, 2, 15))

    # 15 of 29 days: 18.00 -> 9.31 ; 7.00 -> 3.62 ; tax on 12.93 = 1.07
    assert _amounts(invoice) == (Decimal("9.31"), Decimal("3.62"))
    assert invoice.tax_total == Decimal("1.07")
    assert invoice.total == Decimal("14.00")


def test_non_leap_february_uses_28_days(service, ana):
    sub = _sub(service, ana, date(2025, 2, 15))
    invoice = service.issue_invoice(sub["id"], 2025, 2, issued_on=date(2025, 2, 15))

    # 14 of 28 days = exactly half
    assert _amounts(invoice) == (Decimal("9.00"), Decimal("3.50"))
    assert invoice.tax_total == Decimal("1.03")
    assert invoice.total == Decimal("13.53")


def test_thirty_day_month_uses_30_days(service, ana):
    sub = _sub(service, ana, date(2025, 4, 11))
    invoice = service.issue_invoice(sub["id"], 2025, 4, issued_on=date(2025, 4, 11))

    # 20 of 30 days: 18.00 -> 12.00 ; 7.00 -> 4.67 ; tax on 16.67 = 1.38
    assert _amounts(invoice) == (Decimal("12.00"), Decimal("4.67"))
    assert invoice.tax_total == Decimal("1.38")
    assert invoice.total == Decimal("18.05")


def test_no_billable_days_means_no_invoice(service, ana):
    sub = _sub(service, ana, date(2025, 4, 1))

    assert service.issue_invoice(sub["id"], 2025, 3, issued_on=date(2025, 3, 1)) is None
    assert service.repo.invoices == {}


def test_subscription_starting_next_year_has_no_invoice_this_month(service, ana):
    sub = _sub(service, ana, date(2026, 1, 5))

    assert service.issue_invoice(sub["id"], 2025, 12, issued_on=date(2025, 12, 1)) is None


def test_proration_applies_to_every_addon(service, ana):
    sub = _sub(service, ana, date(2025, 4, 11), addons=("extra_bag", "grinder"))
    invoice = service.issue_invoice(sub["id"], 2025, 4, issued_on=date(2025, 4, 11))

    addon_lines = [l.amount for l in invoice.lines if l.kind == LineKind.ADDON]
    # 20/30 of 7.00 = 4.67 and of 5.00 = 3.33
    assert addon_lines == [Decimal("4.67"), Decimal("3.33")]


def test_discount_uses_prorated_plan_amount(service, ana):
    sub = _sub(service, ana, date(2025, 3, 15), discount=20)
    invoice = service.issue_invoice(sub["id"], 2025, 3, issued_on=date(2025, 3, 15))

    # plan 9.87 -> 20% = 1.974 -> 1.97 (not 20% of the full 18.00 list price)
    assert invoice.discount_total == Decimal("1.97")
    assert _amounts(invoice) == (Decimal("9.87"), Decimal("3.84"))
    # taxable = 13.71 - 1.97 = 11.74 -> tax 0.97
    assert invoice.tax_total == Decimal("0.97")
    assert invoice.total == Decimal("12.71")


def test_prorated_invoice_is_still_idempotent(service, ana):
    sub = _sub(service, ana, date(2025, 3, 15))
    first = service.issue_invoice(sub["id"], 2025, 3, issued_on=date(2025, 3, 15))
    second = service.issue_invoice(sub["id"], 2025, 3, issued_on=date(2025, 3, 20))

    assert first is second
    assert len(service.repo.invoices) == 1
