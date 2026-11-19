from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from brewbox.models import LineKind


def _invoice(service, customer, discount, plan="starter", addons=("extra_bag",)):
    sub = service.create_subscription(
        customer["id"],
        plan_code=plan,
        addon_codes=addons,
        start_date=date(2025, 1, 1),
        discount_percent=discount,
    )
    return service.issue_invoice(sub["id"], 2025, 1, issued_on=date(2025, 1, 1))


def test_zero_percent_discount_adds_no_discount_line(service, ana):
    invoice = _invoice(service, ana, 0)

    assert invoice.discount_total == Decimal("0.00")
    assert LineKind.DISCOUNT not in [line.kind for line in invoice.lines]
    assert invoice.total == Decimal("27.06")


def test_thirty_percent_discount_is_accepted_and_plan_only(service, ana):
    invoice = _invoice(service, ana, 30)

    # 30% of the 18.00 plan = 5.40 (not 30% of 25.00 = 7.50).
    assert invoice.discount_total == Decimal("5.40")
    # taxable = 18.00 - 5.40 + 7.00 = 19.60 -> tax 1.62
    assert invoice.tax_total == Decimal("1.62")
    assert invoice.total == Decimal("21.22")


@pytest.mark.parametrize("percent", ["30.01", 31, 45, 100])
def test_discount_above_thirty_is_rejected_and_nothing_is_created(service, ana, percent):
    with pytest.raises(ValueError):
        service.create_subscription(
            ana["id"],
            plan_code="starter",
            start_date=date(2025, 1, 1),
            discount_percent=percent,
        )
    assert service.repo.subscriptions == {}


@pytest.mark.parametrize("percent", [-1, "-0.1", "abc", "NaN"])
def test_negative_or_invalid_discount_is_rejected(service, ana, percent):
    with pytest.raises(ValueError):
        service.create_subscription(
            ana["id"],
            plan_code="starter",
            start_date=date(2025, 1, 1),
            discount_percent=percent,
        )
    assert service.repo.subscriptions == {}


def test_one_decimal_discount_is_valid(service, ana):
    invoice = _invoice(service, ana, "12.5")

    # 12.5% of 18.00 = 2.25 ; taxable 22.75 ; tax 1.88 (1.876875 half-up)
    assert invoice.discount_total == Decimal("2.25")
    assert invoice.tax_total == Decimal("1.88")
    assert invoice.total == Decimal("24.63")


def test_discount_is_rounded_half_up(service, ana):
    invoice = _invoice(service, ana, "12.5", plan="daily", addons=())

    # 12.5% of 33.00 = 4.125 -> 4.13 (half-up; banker's rounding would give 4.12)
    assert invoice.discount_total == Decimal("4.13")
    assert invoice.tax_total == Decimal("2.38")
    assert invoice.total == Decimal("31.25")


def test_discount_line_is_negative_and_total_adds_up(service, ana):
    invoice = _invoice(service, ana, 20)

    discount_line = next(l for l in invoice.lines if l.kind == LineKind.DISCOUNT)
    assert discount_line.amount == Decimal("-3.60")
    assert invoice.total == invoice.subtotal - invoice.discount_total + invoice.tax_total
    assert invoice.subtotal == Decimal("25.00")


def test_discount_never_touches_addons_on_a_large_plan(service, ana):
    # Add-ons are never discounted: the discount equals percent * plan only.
    invoice = _invoice(service, ana, 10, plan="connoisseur", addons=("extra_bag", "grinder", "priority"))

    assert invoice.discount_total == Decimal("5.50")
    assert invoice.subtotal == Decimal("71.00")
