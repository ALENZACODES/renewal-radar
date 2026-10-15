from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
import json
import pytest
from renewal.penalty.verification import (
    ReferenceCase, ReferenceError, parse_inputs, verify_case, verify_cases,
    load_cases, save_report,
)

HASH = sha256(b'fictional synthetic reference only').hexdigest()


def case(**overrides):
    doc = {
        'case_id': 'TD_SYNTHETIC_001',
        'inputs': {'balance': '400000', 'annual_rate': '5', 'remaining_months': 24,
                   'lender': 'td', 'documented_discount': '1', 'comparison_posted_rate': '4'},
        'lender_payout': '16000.00', 'payout_date': '2026-06-01',
        'source_kind': 'synthetic', 'evidence_sha256': HASH,
        'evidence_description': 'Explicit fictional calculator reference, not lender data',
    }
    doc.update(overrides)
    return ReferenceCase.from_dict(doc)


def test_synthetic_match_excluded_from_accuracy_stats():
    item = verify_case(case())
    assert item['status'] == 'match'
    assert not item['eligible_for_accuracy_stats']
    report = verify_cases([case()])
    assert report['matched_official_count'] == 0
    assert report['match_rate'] is None
    assert not report['accuracy_claim_supported']


def test_eligible_documented_case_included_but_does_not_claim_certification():
    report = verify_cases([case(source_kind='dated_payout_statement')])
    assert report['evaluated_official_count'] == 1
    assert report['matched_official_count'] == 1
    assert report['match_rate'] == '1'
    assert 'does not certify' in report['disclaimer']


def test_variance_above_tolerance_is_flagged():
    r = verify_cases([case(lender_payout='18000', source_kind='official_calculator')])
    assert r['results'][0]['status'] == 'variance'
    assert r['results'][0]['difference'] == '-2000.00'
    assert not r['accuracy_claim_supported']


def test_penalty_only_scope_excludes_fees():
    item = case(lender_charge_scope='penalty_only', inputs={
        'balance': '400000', 'annual_rate': '5', 'remaining_months': 24,
        'lender': 'td', 'documented_discount': '1', 'comparison_posted_rate': '4',
        'discharge_fee': '250',
    })
    assert verify_case(item)['estimate'] == '16000.00'


def test_missing_comparison_is_not_recorded_as_variance():
    item = case(inputs={'balance':'400000', 'annual_rate':'5', 'remaining_months':24, 'lender':'td'})
    result = verify_case(item)
    assert result['status'] == 'insufficient_evidence'
    assert result['estimate'] is None
    assert not result['eligible_for_accuracy_stats']


@pytest.mark.parametrize('invalid', ['NaN','Infinity','-Infinity','hello',None,True])
def test_invalid_decimal_rejected(invalid):
    with pytest.raises(ReferenceError):
        case(lender_payout=invalid)


def test_invalid_and_future_dates_rejected():
    with pytest.raises(ReferenceError):
        case(payout_date='2029-01-01')
    with pytest.raises(ReferenceError):
        case(payout_date='June 1')


def test_unknown_inputs_rejected():
    with pytest.raises(ReferenceError):
        parse_inputs({'balance':'40000', 'bad_injected_key':'x'})


def test_duplicate_case_ids_rejected():
    with pytest.raises(ReferenceError, match='duplicate'):
        verify_cases([case(),case()])


def test_roundtrip_json_and_report(tmp_path):
    data = [case().to_dict()]
    path = tmp_path / 'cases.json'
    path.write_text(json.dumps(data))
    loaded = load_cases(path)
    assert loaded[0].input.balance == Decimal('400000')
    report = verify_cases(loaded)
    output = tmp_path / 'report.json'
    save_report(output, report)
    assert json.loads(output.read_text())['count'] == 1


def test_bad_evidence_sha_rejected():
    with pytest.raises(ReferenceError):
        case(evidence_sha256='1234')


def test_nonmatching_case_is_preserved():
    report = verify_cases([case(lender_payout='17000')])
    assert report['results'][0]['absolute_error'] == '1000.00'
    assert report['count'] == 1
