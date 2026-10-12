"""Cross-field consistency checks on extracted statement values."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..domain.mortgage_math import scheduled_payment
from .fields import FieldHit

D = Decimal
PAYMENT_TOLERANCE = 0.03      # 3% covers rounding and payment-date conventions


@dataclass(frozen=True)
class Check:
    code: str
    status: str          # pass | warn | fail
    message: str
    fields: tuple[str, ...]

    def as_dict(self) -> dict:
        return {'code': self.code, 'status': self.status, 'message': self.message,
                'fields': list(self.fields)}


def run_checks(hits: dict[str, FieldHit], today: date) -> list[Check]:
    out: list[Check] = []
    v = {k: h.value for k, h in hits.items()}
    if 'maturity_date' in v:
        maturity: date = v['maturity_date']
        if maturity < today:
            out.append(Check('maturity_past', 'warn',
                             f'Maturity {maturity.isoformat()} is in the past; is this an older statement?',
                             ('maturity_date',)))
        elif (maturity - today).days > 3660:
            out.append(Check('maturity_far', 'warn', 'Maturity is more than ten years away.',
                             ('maturity_date',)))
        else:
            out.append(Check('maturity_window', 'pass', 'Maturity date is plausible.', ('maturity_date',)))
    if {'rate_pct', 'renewal_rate_pct'} <= v.keys() and v['rate_pct'] == v['renewal_rate_pct']:
        out.append(Check('rate_duplicate', 'warn',
                         'Current and renewal rate are identical; one label may have matched the other.',
                         ('rate_pct', 'renewal_rate_pct')))
    if {'term_months', 'amortization_months'} <= v.keys() and v['term_months'] > v['amortization_months']:
        out.append(Check('term_exceeds_amortization', 'fail',
                         'Term is longer than the amortization; one of them was misread.',
                         ('term_months', 'amortization_months')))
    needed = {'balance', 'rate_pct', 'amortization_months', 'payment'}
    if needed <= v.keys():
        freq = v.get('frequency', 'monthly')
        kind = v.get('rate_type', 'fixed')
        try:
            expected = scheduled_payment(float(v['balance']), float(v['rate_pct']),
                                         int(v['amortization_months']), freq, kind)
        except ValueError:
            expected = None
        if expected:
            gap = abs(float(v['payment']) - expected) / expected
            status = 'pass' if gap <= PAYMENT_TOLERANCE else 'warn'
            out.append(Check('payment_consistent', status,
                             f'Expected about ${expected:,.2f} per {freq} payment from balance, rate '
                             f'and amortization; statement shows ${float(v["payment"]):,.2f}'
                             + ('' if status == 'pass' else ' (may include tax or insurance, or a field was misread)')
                             + '.', tuple(sorted(needed))))
    return out
