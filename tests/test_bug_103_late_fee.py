from __future__ import annotations

from datetime import date
from decimal import Decimal

from brewbox.models import InvoiceStatus, LineKind


def _invoice(service, starter_sub, issued_on=date(2025, 1, 1)):
    return service.issue_invoice(
        starter_sub["id"], issued_on.year, issued_on.month, issued_on=issued_on
    )


def _late_fee_lines(invoice):
    return [l for l in invoice.lines if l.kind == LineKind.LATE_FEE]


def test_due_date_is_fourteen_days_after_issue(service, starter_sub):
    assert _invoice(service, starter_sub).due_on == date(2025, 1, 15)


def test_no_fee_before_or_on_the_due_date(service, starter_sub):
    invoice = _invoice(service, starter_sub)

    service.apply_late_fee(invoice.id, as_of=date(2025, 1, 10))
    service.apply_late_fee(invoice.id, as_of=date(2025, 1, 15))

    assert invoice.late_fee == Decimal("0.00")
    assert _late_fee_lines(invoice) == []


def test_no_fee_on_due_date_plus_five(service, starter_sub):
    invoice = _invoice(service, starter_sub)

    service.apply_late_fee(invoice.id, as_of=date(2025, 1, 20))

    assert invoice.late_fee == Decimal("0.00")
    assert invoice.total == Decimal("27.06")


def test_fee_applies_on_due_date_plus_six(service, starter_sub):
    invoice = _invoice(service, starter_sub)

    service.apply_late_fee(invoice.id, as_of=date(2025, 1, 21))

    assert invoice.late_fee == Decimal("10.00")
    assert len(_late_fee_lines(invoice)) == 1
    assert invoice.total == Decimal("37.06")
    assert invoice.amount_due == Decimal("37.06")


def test_fee_applies_much_later_too(service, starter_sub):
    invoice = _invoice(service, starter_sub)

    service.apply_late_fee(invoice.id, as_of=date(2025, 3, 1))

    assert invoice.late_fee == Decimal("10.00")


def test_fee_is_applied_once_per_invoice_even_after_many_runs(service, starter_sub):
    invoice = _invoice(service, starter_sub)

    for day in (date(2025, 1, 21), date(2025, 1, 22), date(2025, 2, 15)):
        service.apply_late_fee(invoice.id, as_of=day)

    assert invoice.late_fee == Decimal("10.00")
    assert len(_late_fee_lines(invoice)) == 1
    assert invoice.total == Decimal("37.06")


def test_fee_is_not_taxed(service, starter_sub):
    invoice = _invoice(service, starter_sub)
    tax_before = invoice.tax_total

    service.apply_late_fee(invoice.id, as_of=date(2025, 1, 21))

    assert invoice.tax_total == tax_before == Decimal("2.06")
    assert invoice.subtotal == Decimal("25.00")


def test_paid_invoice_never_gets_a_fee(service, starter_sub):
    invoice = _invoice(service, starter_sub)
    service.record_payment(invoice.id, paid_on=date(2025, 1, 18))

    service.apply_late_fee(invoice.id, as_of=date(2025, 2, 28))

    assert invoice.status == InvoiceStatus.PAID
    assert invoice.late_fee == Decimal("0.00")
    assert _late_fee_lines(invoice) == []


def test_payment_after_fee_does_not_trigger_a_second_fee(service, starter_sub):
    invoice = _invoice(service, starter_sub)
    service.apply_late_fee(invoice.id, as_of=date(2025, 1, 21))
    service.record_payment(invoice.id, paid_on=date(2025, 1, 22))

    service.apply_late_fee(invoice.id, as_of=date(2025, 2, 21))

    assert invoice.status == InvoiceStatus.PAID
    assert invoice.total == Decimal("37.06")
    assert len(_late_fee_lines(invoice)) == 1


def test_partial_payment_keeps_invoice_open_and_fee_still_applies(service, starter_sub):
    invoice = _invoice(service, starter_sub)
    service.record_payment(invoice.id, amount="10.00", paid_on=date(2025, 1, 10))
    assert invoice.status == InvoiceStatus.ISSUED
    assert invoice.amount_due == Decimal("17.06")

    service.apply_late_fee(invoice.id, as_of=date(2025, 1, 20))
    assert invoice.late_fee == Decimal("0.00")

    service.apply_late_fee(invoice.id, as_of=date(2025, 1, 21))
    assert invoice.late_fee == Decimal("10.00")
    assert invoice.amount_due == Decimal("27.06")


def test_grace_period_is_counted_in_calendar_days_across_month_end(service, starter_sub):
    invoice = _invoice(service, starter_sub, issued_on=date(2025, 1, 25))
    assert invoice.due_on == date(2025, 2, 8)

    service.apply_late_fee(invoice.id, as_of=date(2025, 2, 13))
    assert invoice.late_fee == Decimal("0.00")

    service.apply_late_fee(invoice.id, as_of=date(2025, 2, 14))
    assert invoice.late_fee == Decimal("10.00")
