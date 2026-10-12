"""Published lead score. Uses only renewal facts, never personal attributes."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

D = Decimal


@dataclass(frozen=True)
class LeadFacts:
    renewal_date: date | None
    balance: D | None
    current_rate: D | None
    market_rate: D | None
    has_statement: bool
    completed_analysis: bool


@dataclass(frozen=True)
class LeadScore:
    score: int
    band: str              # hot | warm | nurture
    parts: dict[str, int]


def score_lead(f: LeadFacts, today: date) -> LeadScore:
    parts: dict[str, int] = {}
    if f.renewal_date is not None:
        days = (f.renewal_date - today).days
        parts['timing'] = 40 if 0 <= days <= 120 else 25 if 120 < days <= 240 else 10 if days > 240 else 30
    else:
        parts['timing'] = 5
    if f.balance is not None and f.current_rate is not None and f.market_rate is not None:
        annual = f.balance * max(D(0), f.current_rate - f.market_rate) / D(100)
        parts['savings'] = int(min(D(30), annual / D(150)))
    else:
        parts['savings'] = 0
    parts['readiness'] = (15 if f.has_statement else 0) + (15 if f.completed_analysis else 0)
    total = min(100, sum(parts.values()))
    band = 'hot' if total >= 70 else 'warm' if total >= 40 else 'nurture'
    return LeadScore(total, band, parts)
