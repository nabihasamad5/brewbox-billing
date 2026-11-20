\# Submission



\## Repository



\- Remote URL: https://github.com/nabihasamad5/brewbox-billing

\- Default branch: `main`



\## Pull requests



| Ticket | Branch | PR link | Key commits |

|---|---|---|---|

| BUG-101 | `bugfix/BUG-101-discount-scope` | https://github.com/nabihasamad5/brewbox-billing/pull/1 | 150202c (test), 4b7c33d (fix) |

| BUG-102 | `bugfix/BUG-102-calendar-proration` | https://github.com/nabihasamad5/brewbox-billing/pull/2 | 5ab9926 (test), bc92a44 (fix) |

| BUG-103 | `bugfix/BUG-103-late-fee-grace` | https://github.com/nabihasamad5/brewbox-billing/pull/3 | ec37d0e (test), b7253f0 (fix) |

| FEAT-201 | `feature/FEAT-201-pause-resume` | https://github.com/nabihasamad5/brewbox-billing/pull/4 | 31f520b (test), e22d0bf (feat) |

| FEAT-202 | `feature/FEAT-202-referral-credits` | https://github.com/nabihasamad5/brewbox-billing/pull/5 | 2ab1cef (test), 77d767a (feat) |



\## Test evidence



\- Command: `pytest`

\- Result: 116 passed

\- Tests added: 102 new tests across 5 files (`tests/test\_bug\_101\_discount.py`, `tests/test\_bug\_102\_proration.py`, `tests/test\_bug\_103\_late\_fee.py`, `tests/test\_feat\_201\_pause.py`, `tests/test\_feat\_202\_referrals.py`). The original 14 tests are unchanged and pass.



\## Design notes



\### BUG-101 - discount scope



The discount is calculated from the prorated plan amount only; add-ons are never discounted. Percentages are validated when the subscription is created: 0 to 30 is accepted, anything above 30 (or negative, or not a number) raises ValueError instead of being clamped, so operators see the mistake. Tax is calculated after the discount and every amount is rounded half-up.



\### BUG-102 - proration



Billable days run from the start date to the end of the month, inclusive, divided by the real number of days in that month (28, 29, 30 or 31). Plan and add-ons use the same factor. Each line is rounded half-up to cents before tax. A full month returns the list price directly, so there is no rounding drift. A month with zero billable days returns None, so no invoice is created.



\### BUG-103 - late fee



There are five full days of grace, so the fee starts on due date + 6. It is a single $10 line per invoice, it is not taxed, and it is never added to a paid invoice. Running it again does nothing (idempotent).



\### FEAT-201 - pause/resume



Pauses are stored on the subscription as inclusive date windows of 7 to 90 days. They are rejected if they overlap, start before the subscription start date, or if the customer has an overdue unpaid invoice (checked against today's date). Billing subtracts paused days from the active days, so a partly paused month is prorated and a fully paused month gives no invoice. Early resume shortens the pause to the day before the resume date and must still leave at least 7 days. Trade-off: a pause that starts in the past is allowed, because the acceptance criteria only restrict the start against the subscription start date.



\### FEAT-202 - referral credits



Referral codes are validated when a customer is created (unknown codes and self-referrals are rejected). When the referee's first invoice becomes fully paid, the referrer gets a credit ledger entry of 10% of (subtotal minus discount), rounded half-up and capped at $50, one per referee. Credits expire after 365 days. When an invoice is issued, unexpired credits are applied after tax, oldest expiry first. The amount due never goes below zero and any unused remainder stays on the ledger. The invoice stays "issued" and is not auto-paid. Trade-off: only the referee's first invoice earns a credit, so paying a later invoice first does not create one.



\## AI assistance



\- Tools used: Claude (Anthropic)

\- What I used them for: Claude wrote the implementation and the tests for all five tickets, and guided me through the Git and GitHub steps. I read the tickets and client threads, ran the tests, created the repository, pushed the branches, opened and merged the pull requests, and reviewed the code.

\- What I verified and can explain without assistance: the Git workflow (branches, commits, pull requests) and the business rules for each ticket as described in the design notes above.

\- I confirm I did not paste the entire repository or assignment into an AI tool:

&#x20; no. I uploaded the repository to Claude, and I am disclosing that here.

