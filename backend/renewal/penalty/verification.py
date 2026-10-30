"""Evidence-based lender-payout reconciliation.

The penalty engine produces *estimates*, not lender-certified payouts. This
module compares immutable reference cases against dated written payout figures,
keeps provenance, and explicitly excludes synthetic cases from accuracy claims.
No network requests or personally identifying mortgage documents are required.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from json import dumps, loads
from pathlib import Path
from typing import Any, Iterable

from .engine import calculate_penalty
from .models import Method, PenaltyInputs

DECIMAL_FIELDS = frozenset({
    'balance', 'annual_rate', 'comparison_posted_rate', 'original_posted_rate',
    'documented_discount', 'monthly_payment', 'payout_amount',
    'privilege_available', 'cashback_clawback', 'discharge_fee',
    'administration_fee', 'reinvestment_fee', 'other_fee',
})
ALLOWED_FIELDS = frozenset(f.name for f in fields(PenaltyInputs))
CENTS = Decimal('0.01')
MAX_CASES = 2000


class ReferenceError(ValueError):
    """A reference case lacks the evidence needed for reliable comparison."""


def parse_decimal(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ReferenceError(f'{name} must be a decimal value')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ReferenceError(f'{name} must be a decimal value') from exc
    if not result.is_finite():
        raise ReferenceError(f'{name} must be finite')
    return result


def parse_inputs(raw: dict[str, Any]) -> PenaltyInputs:
    if not isinstance(raw, dict):
        raise ReferenceError('inputs must be an object')
    unknown = set(raw) - ALLOWED_FIELDS
    if unknown:
        raise ReferenceError('unknown mortgage inputs: ' + ', '.join(sorted(unknown)))
    parsed = {}
    for key, value in raw.items():
        if key in DECIMAL_FIELDS and value is not None:
            parsed[key] = parse_decimal(value, key)
        elif key == 'explicit_method' and value is not None:
            try:
                parsed[key] = Method(value)
            except ValueError as exc:
                raise ReferenceError('unknown explicit_method') from exc
        else:
            parsed[key] = value
    try:
        return PenaltyInputs(**parsed)
    except (TypeError, ValueError) as exc:
        raise ReferenceError(str(exc)) from exc


def _date(value: str, field: str) -> date:
    try:
        result = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ReferenceError(f'{field} must be YYYY-MM-DD') from exc
    if result > date.today():
        raise ReferenceError(f'{field} cannot be in the future')
    return result


@dataclass(frozen=True)
class ReferenceCase:
    case_id: str
    input: PenaltyInputs
    lender_payout: Decimal
    payout_date: date
    source_kind: str
    evidence_sha256: str
    evidence_description: str
    allowed_absolute_error: Decimal = Decimal('1.00')
    lender_charge_scope: str = 'penalty_and_fees'
    notes: str = ''

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> 'ReferenceCase':
        if not isinstance(raw, dict):
            raise ReferenceError('reference case must be an object')
        case_id = raw.get('case_id')
        if not isinstance(case_id, str) or not 1 <= len(case_id) <= 96:
            raise ReferenceError('case_id must contain 1..96 characters')
        if any(ch not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for ch in case_id):
            raise ReferenceError('case_id has invalid characters')
        source_kind = raw.get('source_kind')
        if source_kind not in ('official_calculator', 'dated_payout_statement', 'synthetic'):
            raise ReferenceError('source_kind must identify calculator, payout statement, or synthetic fixture')
        evidence_sha256 = raw.get('evidence_sha256', '')
        if not isinstance(evidence_sha256, str) or len(evidence_sha256) != 64:
            raise ReferenceError('evidence_sha256 must be 64 lowercase hexadecimal characters')
        if any(c not in '0123456789abcdef' for c in evidence_sha256):
            raise ReferenceError('evidence_sha256 must be lowercase hexadecimal')
        description = raw.get('evidence_description', '')
        if not isinstance(description, str) or not description.strip() or len(description) > 1000:
            raise ReferenceError('evidence_description required and must be at most 1000 characters')
        payout = parse_decimal(raw.get('lender_payout'), 'lender_payout')
        tolerance = parse_decimal(raw.get('allowed_absolute_error', '1.00'), 'allowed_absolute_error')
        if payout < 0 or tolerance < 0 or tolerance > Decimal('100000'):
            raise ReferenceError('payout and tolerance must be non-negative and tolerance bounded')
        scope = raw.get('lender_charge_scope', 'penalty_and_fees')
        if scope not in ('penalty_only', 'penalty_and_fees'):
            raise ReferenceError('unsupported lender_charge_scope')
        return cls(case_id, parse_inputs(raw.get('inputs')), payout,
                   _date(raw.get('payout_date'), 'payout_date'), source_kind,
                   evidence_sha256, description, tolerance, scope,
                   str(raw.get('notes', ''))[:1000])

    def to_dict(self) -> dict[str, Any]:
        inputs = {}
        for key, value in vars(self.input).items():
            if isinstance(value, Decimal):
                inputs[key] = str(value)
            elif isinstance(value, Method):
                inputs[key] = value.value
            else:
                inputs[key] = value
        return {
            'case_id': self.case_id, 'inputs': inputs,
            'lender_payout': str(self.lender_payout),
            'payout_date': self.payout_date.isoformat(),
            'source_kind': self.source_kind,
            'evidence_sha256': self.evidence_sha256,
            'evidence_description': self.evidence_description,
            'allowed_absolute_error': str(self.allowed_absolute_error),
            'lender_charge_scope': self.lender_charge_scope,
            'notes': self.notes,
        }


def verify_case(case: ReferenceCase) -> dict[str, Any]:
    result = calculate_penalty(case.input)
    estimate = result.core_charge if case.lender_charge_scope == 'penalty_only' else result.total_estimate
    if estimate is None:
        return {
            'case_id': case.case_id, 'status': 'insufficient_evidence',
            'eligible_for_accuracy_stats': False,
            'missing_fields': list(result.missing_fields),
            'estimate': None, 'reference': str(case.lender_payout),
            'profile_version': result.profile_version,
            'warnings': list(result.warnings),
        }
    difference = estimate - case.lender_payout
    absolute_error = abs(difference)
    matched = absolute_error <= case.allowed_absolute_error
    is_official = case.source_kind != 'synthetic'
    return {
        'case_id': case.case_id,
        'status': 'match' if matched else 'variance',
        'eligible_for_accuracy_stats': is_official,
        'source_kind': case.source_kind,
        'estimate': str(estimate),
        'reference': str(case.lender_payout),
        'difference': str(difference),
        'absolute_error': str(absolute_error),
        'tolerance': str(case.allowed_absolute_error),
        'method': result.method,
        'profile_version': result.profile_version,
        'evidence_sha256': case.evidence_sha256,
        'payout_date': case.payout_date.isoformat(),
        'warnings': list(result.warnings),
    }


def verify_cases(cases: Iterable[ReferenceCase]) -> dict[str, Any]:
    seen = set()
    results = []
    for case in cases:
        if len(results) >= MAX_CASES:
            raise ReferenceError(f'maximum {MAX_CASES} reference cases per batch')
        if case.case_id in seen:
            raise ReferenceError('duplicate case_id: ' + case.case_id)
        seen.add(case.case_id)
        results.append(verify_case(case))
    eligible = [r for r in results if r['eligible_for_accuracy_stats']]
    comparisons = [r for r in eligible if r['status'] in ('match', 'variance')]
    matches = sum(r['status'] == 'match' for r in comparisons)
    absolute_errors = [Decimal(r['absolute_error']) for r in comparisons]
    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'count': len(results),
        'eligible_evidence_count': len(eligible),
        'evaluated_official_count': len(comparisons),
        'matched_official_count': matches,
        'match_rate': str(Decimal(matches) / len(comparisons)) if comparisons else None,
        'mean_absolute_error': str(sum(absolute_errors) / len(absolute_errors)) if absolute_errors else None,
        'accuracy_claim_supported': bool(comparisons) and matches == len(comparisons),
        'disclaimer': 'Matching sample lender cases does not certify an exact payout calculation. Obtain written lender confirmation.',
        'results': results,
    }


def load_cases(path: Path) -> list[ReferenceCase]:
    if path.stat().st_size > 4_000_000:
        raise ReferenceError('reference JSON is too large')
    content = loads(path.read_text(encoding='utf-8'))
    if not isinstance(content, list):
        raise ReferenceError('reference JSON must be an array')
    return [ReferenceCase.from_dict(item) for item in content]


def save_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
