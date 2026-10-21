"""Prices, plans and credit amounts: the one file to edit before launch.

Every number here is a PLACEHOLDER until the business signs them off
(MORNING.md, decisions). One credit pays for $1 of vendor spend as the
ledger records it.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Plan:
    plan_id: str
    name: str
    credits: float           # included each month; unused credits lapse at the month's end
    usd: float               # price a month
    inr: float
    blurb: str


# Free credits every new account starts with (they do not lapse). AVE_TRIAL_CREDITS overrides.
TRIAL_CREDITS = float(os.environ.get("AVE_TRIAL_CREDITS") or 5.0)
INR_PER_USD = 84.0
TOPUP_MARKUP = 1.2           # a top-up credit costs $1.20 (the margin on vendor cost)
TOPUPS = (10, 25, 50)        # top-up packs, in credits
TOPUP_MONTHS = 12            # a top-up's credits lapse this many months after it was bought

PLANS = {p.plan_id: p for p in (
    Plan("starter", "Starter", 15.0, 19.0, 1599.0, "For one person trying a few videos a month."),
    Plan("studio", "Studio", 50.0, 59.0, 4999.0, "For a small team shipping every week."),
    Plan("agency", "Agency", 160.0, 179.0, 14999.0, "For agencies running campaigns for clients."),
)}
