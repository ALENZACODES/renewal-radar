from datetime import date
from decimal import Decimal as D

import pytest

from renewal.documents.redact import redact
from renewal.documents.values import parse_date, parse_money, parse_months, parse_percent


@pytest.mark.parametrize('text,expected', [
    (': $412,345.67', D('412345.67')), ('450 000,00 $', D('450000.00')), ('450 000 $', D('450000')),
    ('$2,950', D('2950')), ('450.000,00', D('450000.00')), ('\u00a0412\u202f345,67 $', D('412345.67')),
    ('balance 1,234,567.89 owing', D('1234567.89')), ('for 5 years', None), ('$75', D('75')),
])
def test_money(text, expected):
    assert parse_money(text) == expected


@pytest.mark.parametrize('text,expected', [
    ('5.29%', D('5.29')), ('5,49 %', D('5.49')), ('rate 4.8400 %', D('4.8400')),
    ('save 50%', None), ('none', None)])
def test_percent(text, expected):
    assert parse_percent(text) == expected


@pytest.mark.parametrize('text,expected', [
    ('March 1, 2027', date(2027, 3, 1)), ('Mar. 1st 2027', date(2027, 3, 1)),
    ('2027-03-01', date(2027, 3, 1)), ('1er mars 2027', date(2027, 3, 1)),
    ('15 février 2027', date(2027, 2, 15)), ('15 fevrier 2027', date(2027, 2, 15)),
    ('15 March 2027', date(2027, 3, 15)), ('03/15/2027', date(2027, 3, 15)),
    ('15/03/2027', date(2027, 3, 15)), ('no date', None), ('2027-02-30', None)])
def test_dates(text, expected):
    assert parse_date(text) == expected


def test_ambiguous_numeric_date_honours_day_first():
    assert parse_date('03/04/2027') == date(2027, 3, 4)
    assert parse_date('03/04/2027', day_first=True) == date(2027, 4, 3)


def test_first_date_in_text_wins():
    assert parse_date('issued 2026-09-01, matures March 1, 2027') == date(2026, 9, 1)


@pytest.mark.parametrize('text,expected', [
    ('19 years 6 months', 234), ('22 ans', 264), ('25 ans et 3 mois', 303), ('60 months', 60),
    ('5-year fixed', 60), ('five-year', 60), ('cinq ans', 60), ('soon', None)])
def test_months(text, expected):
    assert parse_months(text) == expected


def test_redact_labelled_and_long_numbers():
    r = redact('Mortgage account number: 0123 4567 8901\nCard 4111-1111-1111-1111\nSIN 046 454 286')
    assert '0123 4567' not in r.text and r.text.count('8901') == 1
    assert '4111-1111' not in r.text and '1111' in r.text
    assert '046 454 286' not in r.text
    assert r.masked == 3


def test_redact_leaves_amounts_rates_and_dates():
    text = 'Balance $412,345.67 at 5.29% on 2027-03-01, payment 2 950,12 $, ref 1234'
    assert redact(text).text == text
    assert redact(text).masked == 0


def test_redact_french_label():
    assert '81234567' not in redact('Numéro de prêt : 81234567').text
