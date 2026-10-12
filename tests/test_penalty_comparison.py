from decimal import Decimal as D

import pytest

from renewal.penalty.comparison import (NoComparisonRate, TermRule, select_comparison_rate,
                                        selection_spread)

TABLE = {12: D('6.00'), 24: D('5.90'), 36: D('6.05'), 60: D('6.49')}


def test_exact_term_short_circuits_every_rule():
    for rule in TermRule:
        sel = select_comparison_rate(TABLE, 36, rule)
        assert sel.rate == D('6.05') and sel.terms_used == (36,)


@pytest.mark.parametrize('months,rule,expected,terms', [
    (17, TermRule.NEAREST, D('6.00'), (12,)),
    (19, TermRule.NEAREST, D('5.90'), (24,)),
    (18, TermRule.NEAREST, D('6.00'), (12,)),
    (18, TermRule.NEAREST_LONGER_ON_TIE, D('5.90'), (24,)),
    (17, TermRule.ROUND_DOWN, D('6.00'), (12,)),
    (17, TermRule.ROUND_UP, D('5.90'), (24,)),
    (48, TermRule.INTERPOLATE, D('6.27'), (36, 60)),
])
def test_rules(months, rule, expected, terms):
    sel = select_comparison_rate(TABLE, months, rule)
    assert sel.rate == expected
    assert sel.terms_used == terms


def test_round_down_below_shortest_term_fails():
    with pytest.raises(NoComparisonRate):
        select_comparison_rate(TABLE, 6, TermRule.ROUND_DOWN)


def test_round_up_beyond_longest_term_fails():
    with pytest.raises(NoComparisonRate):
        select_comparison_rate(TABLE, 84, TermRule.ROUND_UP)


def test_interpolate_never_extrapolates():
    sel = select_comparison_rate(TABLE, 6, TermRule.INTERPOLATE)
    assert sel.rate == D('6.00')
    assert 'not extrapolated' in sel.note


def test_spread_omits_unsupported_rules():
    spread = selection_spread(TABLE, 6)
    assert 'round_down' not in spread
    assert spread['round_up'].rate == D('6.00')


@pytest.mark.parametrize('table', [{}, {0: D('5')}, {12: D('-1')}, {12: D('31')}])
def test_table_validation(table):
    with pytest.raises((ValueError, NoComparisonRate)):
        select_comparison_rate(table, 12)


def test_remaining_months_must_be_positive():
    with pytest.raises(ValueError):
        select_comparison_rate(TABLE, 0)


def test_accepts_string_and_float_rates():
    sel = select_comparison_rate({12: '5.5', 24: 5.25}, 24)
    assert sel.rate == D('5.25')
    assert sel.as_dict()['rate'] == '5.25'
