from datetime import date
from decimal import Decimal as D

import pytest

from renewal.broker.pipeline import (ClientFacts, InvalidTransition, Stage, Window, check_transition,
                                     priority, window)

TODAY = date(2026, 10, 12)


@pytest.mark.parametrize('renewal,expected', [
    (None, Window.UNKNOWN), (date(2026, 10, 1), Window.OVERDUE), (date(2026, 10, 12), Window.UNDER_30),
    (date(2026, 11, 10), Window.UNDER_30), (date(2026, 11, 11), Window.D30_90),
    (date(2027, 1, 9), Window.D30_90), (date(2027, 1, 10), Window.D90_180), (date(2027, 6, 1), Window.LATER)])
def test_windows(renewal, expected):
    assert window(renewal, TODAY) is expected


def test_transitions():
    check_transition(Stage.NEW, Stage.ANALYSIS_READY)
    check_transition(Stage.NEGOTIATING, Stage.SWITCHED)
    check_transition(Stage.CLOSED_LOST, Stage.NEW)
    with pytest.raises(InvalidTransition, match='allowed: none'):
        check_transition(Stage.RENEWED, Stage.NEW)
    with pytest.raises(InvalidTransition):
        check_transition(Stage.NEW, Stage.SWITCHED)


def test_priority_combines_urgency_stage_and_rate_gap():
    facts = ClientFacts(date(2026, 11, 1), Stage.ANALYSIS_READY, D('500000'), D('5.49'), D('4.49'))
    p = priority(facts, TODAY)
    # 45 urgency + 20 stage + min(25, 5000/200) = 90
    assert p.score == 90
    assert any('rate gap +1.00' in r and '$5,000/yr' in r for r in p.reasons)


def test_priority_no_gap_points_when_rate_below_market():
    p = priority(ClientFacts(date(2027, 6, 1), Stage.NEW, D('300000'), D('4.00'), D('6.00')), TODAY)
    assert p.score == 15
    assert not any('rate gap' in r for r in p.reasons)


def test_priority_missing_facts_and_closed():
    p = priority(ClientFacts(None, Stage.NEW), TODAY)
    assert p.score == 20 and 'missing balance or rate' in p.reasons
    assert priority(ClientFacts(date(2026, 10, 20), Stage.SWITCHED), TODAY).score == 0


def test_priority_capped_at_100():
    facts = ClientFacts(date(2026, 10, 1), Stage.NEGOTIATING, D('5000000'), D('9'), D('4'))
    assert priority(facts, TODAY).score == 90  # 45 + 20 + 25; already under the cap
    assert priority(facts, TODAY).score <= 100
