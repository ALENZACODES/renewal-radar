"""Field labels used on Canadian mortgage statements and renewal letters (EN and FR)."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: str                        # money | percent | date | months | frequency | rate_type
    labels: tuple[tuple[str, str], ...]   # (language, regex)
    required: bool = False


def _l(*pairs: tuple[str, str]) -> tuple[tuple[str, str], ...]:
    return pairs


FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec('balance', 'money', _l(
        ('en', r'(?:outstanding|principal|current|mortgage|remaining)\s+(?:principal\s+)?balance'),
        ('en', r'balance\s+(?:at\s+(?:maturity|renewal)|as\s+of|owing|outstanding)'),
        ('en', r'principal\s+(?:amount\s+)?(?:outstanding|owing|remaining)'),
        ('fr', r'solde\s+(?:du\s+)?(?:capital|prêt|hypothécaire|impayé|à\s+l.échéance)'),
        ('fr', r'capital\s+(?:restant|impayé)')), required=True),
    FieldSpec('rate_pct', 'percent', _l(
        ('en', r'(?:current\s+|annual\s+|contract\s+)?interest\s+rate'),
        ('en', r'current\s+rate'),
        ('fr', r'taux\s+d.intérêt(?:\s+annuel|\s+actuel)?'),
        ('fr', r'taux\s+(?:actuel|annuel)')), required=True),
    FieldSpec('renewal_rate_pct', 'percent', _l(
        ('en', r'renewal\s+(?:offer|interest\s+rate|rate)|offered\s+rate|new\s+(?:interest\s+)?rate'),
        ('fr', r'taux\s+(?:de\s+)?renouvellement|taux\s+offert|nouveau\s+taux'))),
    FieldSpec('maturity_date', 'date', _l(
        ('en', r'maturity\s+date|matures\s+on|term\s+(?:ends|expiry|end\s+date)|renewal\s+date'),
        ('fr', r'date\s+d.échéance|échéance\s+du\s+terme|date\s+de\s+renouvellement|vient\s+à\s+échéance')),
        required=True),
    FieldSpec('payment', 'money', _l(
        ('en', r'(?:regular\s+|scheduled\s+)?(?:monthly|bi-?weekly|weekly|semi-?monthly)?\s*'
               r'(?:principal\s+and\s+interest\s+)?payment(?:\s+amount)?'),
        ('fr', r'(?:montant\s+du\s+)?versement(?:\s+régulier|\s+mensuel)?|paiement\s+(?:mensuel|régulier)'))),
    FieldSpec('term_months', 'months', _l(
        ('en', r'(?:current\s+|renewal\s+)?term(?:\s+length)?'),
        ('fr', r'(?:durée\s+du\s+)?terme')), required=True),
    FieldSpec('amortization_months', 'months', _l(
        ('en', r'(?:remaining\s+)?amorti[sz]ation(?:\s+period)?'),
        ('fr', r'(?:période\s+d.)?amortissement(?:\s+restant)?'))),
    FieldSpec('frequency', 'frequency', _l(
        ('en', r'payment\s+frequency|payments?\s+(?:are\s+)?(?:made\s+)?'),
        ('fr', r'fréquence\s+des\s+versements|fréquence'))),
    FieldSpec('rate_type', 'rate_type', _l(
        ('en', r'(?:rate|mortgage|product)\s+type|interest\s+type'),
        ('fr', r'type\s+de\s+(?:taux|prêt)'))),
    FieldSpec('prepayment_lump_sum_pct', 'percent', _l(
        ('en', r'(?:annual\s+)?(?:lump[- ]sum|prepayment)\s+(?:privilege|allowance|option)?'),
        ('fr', r'remboursement\s+anticipé|montant\s+forfaitaire'))),
)

BY_NAME: dict[str, FieldSpec] = {f.name: f for f in FIELDS}

FREQUENCIES: tuple[tuple[str, str], ...] = (
    (r'accelerated\s+bi-?weekly|aux\s+deux\s+semaines\s+accéléré', 'accelerated-biweekly'),
    (r'accelerated\s+weekly|hebdomadaire\s+accéléré', 'accelerated-weekly'),
    (r'semi-?monthly|bimensuel', 'semi-monthly'),
    (r'bi-?weekly|aux\s+deux\s+semaines|toutes\s+les\s+deux\s+semaines', 'biweekly'),
    (r'\bweekly\b|hebdomadaire', 'weekly'),
    (r'\bmonthly\b|mensuel', 'monthly'),
)


def compiled(spec: FieldSpec) -> list[tuple[str, re.Pattern[str]]]:
    return [(lang, re.compile(rf'(?<!\w)(?:{rx})', re.I)) for lang, rx in spec.labels]
