from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from brewbox.billing import referral_credit_amount
from brewbox.models import InvoiceStatus


@pytest.fixture
def referrer(service, ana):
    """Ana (code ANA-123) with a plain starter subscription."""
    sub = service.create_subscription(ana["id"], "starter", start_date=date(2025, 1, 1))
    return {"customer": ana, "sub": sub}


def _referee(service, name="Ben", code="BEN-1", email="ben@example.com", referred_by="ANA-123"):
    return service.create_customer(name, email, code, referred_by=referred_by)


def _referee_invoice(service, referee, addons=("extra_bag",), discount=0, plan="starter"):
    sub = service.create_subscription(
        referee["id"], plan, list(addons), start_date=date(2025, 1, 1), discount_percent=discount
    )
    invoice = service.issue_invoice(sub["id"], 2025, 1, issued_on=date(2025, 1, 1))
    return sub, invoice


# ----------------------------------------------------------- customer creation
def test_unknown_referral_code_is_rejected(service):
    with pytest.raises(ValueError):
        service.create_customer("Ben", "ben@example.com", "BEN-1", referred_by="NOPE-1")
    assert service.repo.customers == {}


def test_self_referral_is_rejected(service):
    with pytest.raises(ValueError):
        service.create_customer("Ben", "ben@example.com", "BEN-1", referred_by="ben-1")
    assert service.repo.customers == {}


def test_referral_code_lookup_is_case_insensitive(service, ana):
    ben = service.create_customer("Ben", "ben@example.com", "BEN-1", referred_by="ana-123")

    assert ben["referred_by"] == "ANA-123"


def test_customer_without_referral_is_still_fine(service, ana):
    assert ana["referred_by"] is None


# ------------------------------------------------------------ amount rules
@pytest.mark.parametrize(
    "base, expected",
    [
        ("0.00", "0.00"),
        ("18.00", "1.80"),
        ("16.20", "1.62"),
        ("16.25", "1.63"),  # 1.625 -> half-up
        ("16.24", "1.62"),
        ("499.94", "49.99"),
        ("500.00", "50.00"),
        ("500.10", "50.00"),  # capped
        ("1000.00", "50.00"),
    ],
)
def test_referral_credit_amount_rounding_and_cap(base, expected):
    assert referral_credit_amount(Decimal(base)) == Decimal(expected)


# --------------------------------------------------------------- earning
def test_no_credit_while_the_first_invoice_is_only_issued(service, referrer):
    ben = _referee(service)
    _referee_invoice(service, ben)

    assert service.list_credits(referrer["customer"]["id"]) == []
    assert service.credit_balance(referrer["customer"]["id"]) == Decimal("0.00")


def test_partial_payment_does_not_create_a_credit(service, referrer):
    ben = _referee(service)
    _, invoice = _referee_invoice(service, ben)

    service.record_payment(invoice.id, amount="10.00", paid_on=date(2025, 1, 5))

    assert service.list_credits(referrer["customer"]["id"]) == []


def test_credit_is_created_when_first_invoice_is_fully_paid(service, referrer):
    ben = _referee(service)
    _, invoice = _referee_invoice(service, ben)

    service.record_payment(invoice.id, amount="10.00", paid_on=date(2025, 1, 5))
    service.record_payment(invoice.id, paid_on=date(2025, 1, 10))

    credits = service.list_credits(referrer["customer"]["id"])
    assert len(credits) == 1
    credit = credits[0]
    # 10% of the pre-tax 25.00 (plan + add-on), not of the 27.06 total
    assert credit.amount == Decimal("2.50")
    assert credit.remaining == Decimal("2.50")
    assert credit.customer_id == referrer["customer"]["id"]
    assert credit.source_customer_id == ben["id"]
    assert credit.source_invoice_id == invoice.id
    assert credit.issued_on == date(2025, 1, 10)
    assert credit.expires_on == date(2026, 1, 10)


def test_credit_base_is_after_discount(service, referrer):
    ben = _referee(service)
    _, invoice = _referee_invoice(service, ben, addons=(), discount=10)

    service.record_payment(invoice.id, paid_on=date(2025, 1, 10))

    # (18.00 - 1.80) * 10% = 1.62, not 1.80
    assert service.list_credits(referrer["customer"]["id"])[0].amount == Decimal("1.62")


def test_credit_excludes_late_fee_and_tax(service, referrer):
    ben = _referee(service)
    _, invoice = _referee_invoice(service, ben)
    service.apply_late_fee(invoice.id, as_of=date(2025, 1, 21))
    assert invoice.total == Decimal("37.06")

    service.record_payment(invoice.id, paid_on=date(2025, 1, 22))

    assert service.list_credits(referrer["customer"]["id"])[0].amount == Decimal("2.50")


def test_credit_is_capped_at_fifty_dollars(service, referrer):
    ben = _referee(service)
    sub = service.create_subscription(
        ben["id"], "connoisseur", ["extra_bag"] * 70, start_date=date(2025, 1, 1)
    )
    invoice = service.issue_invoice(sub["id"], 2025, 1, issued_on=date(2025, 1, 1))
    assert invoice.subtotal == Decimal("545.00")  # 10% would be 54.50

    service.record_payment(invoice.id, paid_on=date(2025, 1, 10))

    assert service.list_credits(referrer["customer"]["id"])[0].amount == Decimal("50.00")


def test_only_one_credit_per_referee(service, referrer):
    ben = _referee(service)
    sub, first = _referee_invoice(service, ben)
    service.record_payment(first.id, paid_on=date(2025, 1, 10))
    second = service.issue_invoice(sub["id"], 2025, 2, issued_on=date(2025, 2, 1))

    service.record_payment(second.id, paid_on=date(2025, 2, 10))

    assert len(service.list_credits(referrer["customer"]["id"])) == 1


def test_paying_a_later_invoice_first_does_not_earn_a_credit(service, referrer):
    ben = _referee(service)
    sub, first = _referee_invoice(service, ben)
    second = service.issue_invoice(sub["id"], 2025, 2, issued_on=date(2025, 2, 1))

    service.record_payment(second.id, paid_on=date(2025, 2, 10))

    assert first.status == InvoiceStatus.ISSUED
    assert service.list_credits(referrer["customer"]["id"]) == []


def test_customer_without_referrer_earns_nobody_a_credit(service, ana):
    _, invoice = _referee_invoice(service, ana)

    service.record_payment(invoice.id, paid_on=date(2025, 1, 10))

    assert service.repo.credits == {}


def test_each_referee_earns_their_own_credit(service, referrer):
    ben = _referee(service)
    cy = _referee(service, "Cy", "CY-1", "cy@example.com")
    _, ben_invoice = _referee_invoice(service, ben)
    _, cy_invoice = _referee_invoice(service, cy, addons=())

    service.record_payment(ben_invoice.id, paid_on=date(2025, 1, 10))
    service.record_payment(cy_invoice.id, paid_on=date(2025, 1, 11))

    amounts = sorted(c.amount for c in service.list_credits(referrer["customer"]["id"]))
    assert amounts == [Decimal("1.80"), Decimal("2.50")]


# ---------------------------------------------------------------- spending
def _earn(service, referrer, paid_on=date(2025, 1, 10), **kwargs):
    ben = kwargs.pop("referee", None) or _referee(service)
    _, invoice = _referee_invoice(service, ben, **kwargs)
    service.record_payment(invoice.id, paid_on=paid_on)
    return ben, invoice


def test_credit_is_applied_to_referrers_next_invoice_after_tax(service, referrer):
    jan = service.issue_invoice(referrer["sub"]["id"], 2025, 1, issued_on=date(2025, 1, 1))
    _earn(service, referrer)  # 2.50 credit, after Ana's January invoice was issued
    assert jan.credit_applied == Decimal("0.00")

    feb = service.issue_invoice(referrer["sub"]["id"], 2025, 2, issued_on=date(2025, 2, 1))

    # Starter 18.00 + 8.25% tax 1.49 = 19.49 ; credit is a payment, not a discount.
    assert feb.subtotal == Decimal("18.00")
    assert feb.tax_total == Decimal("1.49")
    assert feb.total == Decimal("19.49")
    assert feb.credit_applied == Decimal("2.50")
    assert feb.amount_due == Decimal("16.99")
    assert feb.status == InvoiceStatus.ISSUED
    assert service.credit_balance(referrer["customer"]["id"], as_of=date(2025, 2, 1)) == Decimal("0.00")


def test_credit_is_never_applied_to_the_invoice_that_generated_it(service, referrer):
    ben, invoice = _earn(service, referrer)

    assert invoice.credit_applied == Decimal("0.00")
    assert invoice.customer_id == ben["id"]
    assert service.list_credits(ben["id"]) == []
    assert service.credit_balance(referrer["customer"]["id"]) == Decimal("2.50")


def test_credit_stays_on_account_when_referrer_has_no_invoice(service, referrer):
    _earn(service, referrer)

    assert service.credit_balance(referrer["customer"]["id"], as_of=date(2025, 6, 1)) == Decimal("2.50")


def test_credit_larger_than_invoice_leaves_zero_due_and_a_remainder(service, referrer):
    ben = _referee(service)
    sub = service.create_subscription(
        ben["id"], "connoisseur", ["extra_bag"] * 70, start_date=date(2025, 1, 1)
    )
    big = service.issue_invoice(sub["id"], 2025, 1, issued_on=date(2025, 1, 1))
    service.record_payment(big.id, paid_on=date(2025, 1, 10))  # 50.00 credit

    feb = service.issue_invoice(referrer["sub"]["id"], 2025, 2, issued_on=date(2025, 2, 1))
    assert feb.total == Decimal("19.49")
    assert feb.credit_applied == Decimal("19.49")
    assert feb.amount_due == Decimal("0.00")
    assert feb.status == InvoiceStatus.ISSUED  # not auto-paid
    assert service.credit_balance(referrer["customer"]["id"], as_of=date(2025, 2, 1)) == Decimal("30.51")

    # the remainder carries to the following invoices until used up
    mar = service.issue_invoice(referrer["sub"]["id"], 2025, 3, issued_on=date(2025, 3, 1))
    assert (mar.credit_applied, mar.amount_due) == (Decimal("19.49"), Decimal("0.00"))
    apr = service.issue_invoice(referrer["sub"]["id"], 2025, 4, issued_on=date(2025, 4, 1))
    assert (apr.credit_applied, apr.amount_due) == (Decimal("11.02"), Decimal("8.47"))
    assert service.credit_balance(referrer["customer"]["id"], as_of=date(2025, 4, 1)) == Decimal("0.00")


def test_oldest_expiring_credit_is_used_first(service, referrer):
    ben = _referee(service)
    cy = _referee(service, "Cy", "CY-1", "cy@example.com")
    big_sub = service.create_subscription(
        ben["id"], "connoisseur", ["extra_bag"] * 70, start_date=date(2025, 1, 1)
    )
    big = service.issue_invoice(big_sub["id"], 2025, 1, issued_on=date(2025, 1, 1))
    service.record_payment(big.id, paid_on=date(2025, 2, 20))  # 50.00, expires 2026-02-20
    _earn(service, referrer, paid_on=date(2025, 1, 10), referee=cy, addons=())  # 1.80, expires 2026-01-10

    feb = service.issue_invoice(referrer["sub"]["id"], 2025, 3, issued_on=date(2025, 3, 1))

    assert feb.credit_applied == Decimal("19.49")
    credits = service.list_credits(referrer["customer"]["id"])
    assert [c.expires_on for c in credits] == [date(2026, 1, 10), date(2026, 2, 20)]
    assert [c.remaining for c in credits] == [Decimal("0.00"), Decimal("32.31")]


@pytest.mark.parametrize(
    "issued_on, applied",
    [
        (date(2026, 1, 9), Decimal("2.50")),   # day before expiry: usable
        (date(2026, 1, 10), Decimal("0.00")),  # expiry date: not usable
        (date(2026, 3, 1), Decimal("0.00")),
    ],
)
def test_expired_credit_is_not_applied(service, referrer, issued_on, applied):
    _earn(service, referrer, paid_on=date(2025, 1, 10))  # expires 2026-01-10

    invoice = service.issue_invoice(
        referrer["sub"]["id"], issued_on.year, issued_on.month, issued_on=issued_on
    )

    assert invoice.credit_applied == applied


def test_expired_credit_is_excluded_from_balance_but_kept_in_ledger(service, referrer):
    _earn(service, referrer, paid_on=date(2025, 1, 10))
    ana_id = referrer["customer"]["id"]

    assert service.credit_balance(ana_id, as_of=date(2026, 1, 9)) == Decimal("2.50")
    assert service.credit_balance(ana_id, as_of=date(2026, 1, 10)) == Decimal("0.00")
    assert len(service.list_credits(ana_id)) == 1


def test_credit_does_not_stop_a_late_fee_on_the_remaining_balance(service, referrer):
    _earn(service, referrer)
    feb = service.issue_invoice(referrer["sub"]["id"], 2025, 2, issued_on=date(2025, 2, 1))

    service.apply_late_fee(feb.id, as_of=date(2025, 2, 21))

    assert feb.amount_due == Decimal("26.99")  # 19.49 + 10.00 fee - 2.50 credit


def test_reissue_does_not_spend_the_credit_twice(service, referrer):
    _earn(service, referrer)
    first = service.issue_invoice(referrer["sub"]["id"], 2025, 2, issued_on=date(2025, 2, 1))
    again = service.issue_invoice(referrer["sub"]["id"], 2025, 2, issued_on=date(2025, 2, 2))

    assert again is first
    assert service.list_credits(referrer["customer"]["id"])[0].remaining == Decimal("0.00")
