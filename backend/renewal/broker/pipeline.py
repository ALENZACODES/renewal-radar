"""Broker renewal pipeline rules: stages, transitions, countdown and priority.

Pure functions only; persistence lives in ``dashboard.py``. Priority is a
transparent weighted score so a broker can see why a client is at the top,
never a model output.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

D = Decimal


class Stage(str, Enum):
    NEW = 'new'
    DOCUMENTS_REQUESTED = 'documents_requested'
    ANALYSIS_READY = 'analysis_ready'
    NEGOTIATING = 'negotiating'
    RENEWED = 'renewed'            # stayed with current lender
    SWITCHED = 'switched'          # moved to a new lender
    CLOSED_LOST = 'closed_lost'


CLOSED = frozenset({Stage.RENEWED, Stage.SWITCHED, Stage.CLOSED_LOST})
TRANSITIONS: dict[Stage, frozenset[Stage]] = {
    Stage.NEW: frozenset({Stage.DOCUMENTS_REQUESTED, Stage.ANALYSIS_READY, Stage.CLOSED_LOST}),
    Stage.DOCUMENTS_REQUESTED: frozenset({Stage.ANALYSIS_READY, Stage.CLOSED_LOST}),
    Stage.ANALYSIS_READY: frozenset({Stage.NEGOTIATING, Stage.RENEWED, Stage.SWITCHED, Stage.CLOSED_LOST}),
    Stage.NEGOTIATING: frozenset({Stage.RENEWED, Stage.SWITCHED, Stage.CLOSED_LOST, Stage.ANALYSIS_READY}),
    Stage.RENEWED: frozenset(),
    Stage.SWITCHED: frozenset(),
    Stage.CLOSED_LOST: frozenset({Stage.NEW}),     # a lost client can be reopened
}


class InvalidTransition(ValueError):
    pass


def check_transition(current: Stage, target: Stage) -> None:
    if target not in TRANSITIONS[current]:
        allowed = ', '.join(sorted(s.value for s in TRANSITIONS[current])) or 'none'
        raise InvalidTransition(f'cannot move from {current.value} to {target.value} (allowed: {allowed})')


class Window(str, Enum):
    OVERDUE = 'overdue'
    UNDER_30 = 'under_30_days'
    D30_90 = '30_to_90_days'
    D90_180 = '90_to_180_days'
    LATER = 'over_180_days'
    UNKNOWN = 'no_date'


def window(renewal: date | None, today: date) -> Window:
    if renewal is None:
        return Window.UNKNOWN
    days = (renewal - today).days
    if days < 0:
        return Window.OVERDUE
    if days < 30:
        return Window.UNDER_30
    if days < 90:
        return Window.D30_90
    if days < 180:
        return Window.D90_180
    return Window.LATER


@dataclass(frozen=True)
class ClientFacts:
    renewal_date: date | None
    stage: Stage
    balance: D | None = None
    rate_pct: D | None = None
    market_rate_pct: D | None = None     # comparable posted or offered rate today


@dataclass(frozen=True)
class Priority:
    score: int
    reasons: tuple[str, ...]


# Weights sum to 100 for an open client with every fact present.
URGENCY = {Window.OVERDUE: 45, Window.UNDER_30: 45, Window.D30_90: 35, Window.D90_180: 20,
           Window.LATER: 5, Window.UNKNOWN: 10}
STAGE_PUSH = {Stage.NEW: 10, Stage.DOCUMENTS_REQUESTED: 15, Stage.ANALYSIS_READY: 20,
              Stage.NEGOTIATING: 20}


def priority(facts: ClientFacts, today: date) -> Priority:
    if facts.stage in CLOSED:
        return Priority(0, ('closed',))
    w = window(facts.renewal_date, today)
    score = URGENCY[w]
    reasons = [f'renewal {w.value.replace("_", " ")}']
    score += STAGE_PUSH[facts.stage]
    reasons.append(f'stage {facts.stage.value.replace("_", " ")}')
    if facts.balance is not None and facts.rate_pct is not None and facts.market_rate_pct is not None:
        gap = facts.rate_pct - facts.market_rate_pct
        annual = facts.balance * gap / D(100)
        # $0 -> 0 points, $5,000+/yr of rate difference -> 25 points
        points = int(max(D(0), min(D(25), annual / D(200))))
        if points:
            score += points
            reasons.append(f'rate gap {gap:+.2f} pts (~${annual:,.0f}/yr)')
    elif facts.balance is None or facts.rate_pct is None:
        reasons.append('missing balance or rate')
    return Priority(min(100, score), tuple(reasons))
