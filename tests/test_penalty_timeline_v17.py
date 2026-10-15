from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from renewal.main import app
from renewal.services.penalty_timeline_v17 import (
    PenaltyTimelineRequest, RateBucket, month_date, select_bucket, penalty_timeline,
)


def request(**overrides):
    return PenaltyTimelineRequest(**dict({
        'balance': '200000', 'contract_rate': '5.14', 'remaining_months': 42,
        'amortization_months': 300, 'start_date': '2026-01-31',
        'comparison_rate': '3.75', 'method': 'simple_differential',
    }, **overrides))


def test_curve_uses_existing_engine_and_actual_declining_principal():
    result = penalty_timeline(request())
    assert len(result['points']) == 43
    first, second, last = result['points'][0], result['points'][1], result['points'][-1]
    assert first['penalty']['three_month_interest'] == '2570.00'
    assert first['penalty']['interest_rate_differential'] == '9730.00'
    assert Decimal(second['balance']) < Decimal(first['balance'])
    assert last['penalty']['core_charge'] == '0'
    assert last['remaining_months'] == 0


def test_end_of_month_dates_are_anchored_to_original_day():
    assert month_date(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert month_date(date(2026, 1, 31), 2) == date(2026, 3, 31)
    assert month_date(date(2024, 1, 31), 1) == date(2024, 2, 29)


def test_bucket_ceiling_boundary_and_nearest_tie_are_explicit():
    ladder = [RateBucket(months=12, rate='4'), RateBucket(months=24, rate='5')]
    assert select_bucket(ladder, 13, 'ceiling').months == 24
    assert select_bucket(ladder, 12, 'ceiling').months == 12
    assert select_bucket(ladder, 18, 'nearest').months == 24
    assert select_bucket(ladder, 25, 'ceiling') is None


def test_ladder_changes_are_recorded_without_inventing_future_rates():
    result = penalty_timeline(request(remaining_months=25, ladder=[
        {'months': 12, 'rate': '4.1'}, {'months': 24, 'rate': '4.5'}, {'months': 36, 'rate': '4.7'},
    ]))
    assert result['points'][0]['bucket_months'] == 36
    assert result['points'][1]['bucket_months'] == 24
    assert result['transitions'][0]['month'] == 1
    assert result['transitions'][1]['month'] == 13
    assert result['points'][-1]['bucket_months'] is None


def test_missing_bucket_never_falls_back_to_unrelated_single_comparison_rate():
    result = penalty_timeline(request(ladder=[{'months': 12, 'rate': '4'}]))
    assert result['points'][0]['comparison_rate'] is None
    assert result['points'][0]['penalty']['core_charge'] is None
    assert result['points'][0]['penalty']['status'] == 'floor_only'


def test_missing_discount_keeps_posted_or_pv_final_charge_unknown():
    for method in ['posted_minus_discount', 'present_value']:
        result = penalty_timeline(request(method=method))
        assert result['points'][0]['penalty']['total_estimate'] is None


def test_pv_method_remains_explicitly_illustrative_and_fees_separate():
    result = penalty_timeline(request(method='present_value', discount='1', fees='350'))
    first = result['points'][0]['penalty']
    assert first['method'] == 'present_value'
    assert Decimal(first['total_estimate']) == Decimal(first['core_charge']) + Decimal('350')
    assert result['points'][-1]['penalty']['total_estimate'] == '350.00'
    assert any('illustrative' in note.lower() for note in result['assumptions'])


def test_undocumented_method_is_floor_only_even_with_a_rate():
    first = penalty_timeline(request(method='undocumented'))['points'][0]['penalty']
    assert first['status'] == 'floor_only'
    assert first['core_charge'] is None


def test_variable_closed_model_uses_floor_and_no_fabricated_ird():
    first = penalty_timeline(request(rate_type='variable'))['points'][0]['penalty']
    assert first['controlling_method'] == '3_months'
    assert first['interest_rate_differential'] is None


def test_already_matured_loan_has_one_point_and_only_separate_fees():
    result = penalty_timeline(request(remaining_months=0, fees='350'))
    assert len(result['points']) == 1
    assert result['points'][0]['penalty']['total_estimate'] == '350.00'


def test_repaid_loan_at_final_month_does_not_crash_engine():
    result = penalty_timeline(request(remaining_months=12, amortization_months=12))
    assert result['points'][-1]['penalty']['status'] == 'no_charge_modelled'


@pytest.mark.parametrize('overrides', [
    {'remaining_months': 121}, {'remaining_months': -1}, {'remaining_months': True},
    {'remaining_months': 12.5}, {'balance': 'NaN'}, {'balance': '0'},
    {'contract_rate': 'Infinity'}, {'comparison_rate': '31'}, {'fees': '-1'},
    {'amortization_months': 12}, {'start_date': '2091-01-01'},
    {'method': 'guaranteed'}, {'bucket_rule': 'guess'},
    {'ladder': [{'months': 12, 'rate': '4'}, {'months': 12, 'rate': '5'}]},
])
def test_invalid_or_unbounded_projection_inputs_fail(overrides):
    with pytest.raises(ValidationError):
        request(**overrides)


def test_timeline_api_and_schema_validation():
    with TestClient(app) as http:
        response = http.post('/api/v17/penalty/timeline', json=request().model_dump(mode='json'))
        assert response.status_code == 200
        assert len(response.json()['points']) == 43
        assert http.post('/api/v17/penalty/timeline', json={'balance': -1}).status_code == 422
        assert http.post('/api/v17/penalty/timeline', json={**request().model_dump(mode='json'), 'private_extra': 'no'}).status_code == 422
