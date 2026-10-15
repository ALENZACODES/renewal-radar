import pytest

from renewal.ocr.adapter_benchmark_suite_v15 import (
    AdapterBenchmarkError,
    BASE_MORTGAGE_TEXT,
    BenchmarkCase,
    BenchmarkExpectation,
    apply_ocr_noise,
    build_default_benchmark_cases,
    evaluate_benchmark_case,
    marker_payload,
    paddle_payload,
    recommended_benchmark_actions,
    remove_lines_containing,
    replace_line_value,
    run_adapter_benchmark_suite,
    summarize_benchmark_results,
    thin_rate_text,
)


def case_by_id(cases, id_):
    return next(case for case in cases if case.id == id_)


def test_build_default_benchmark_cases_covers_latest_adapter_shapes():
    cases = build_default_benchmark_cases()
    ids = {case.id for case in cases}
    adapters = {case.adapter for case in cases}

    assert "marker-complete-renewal" in ids
    assert "paddleocr-complete-lines" in ids
    assert "docling-structured-page" in ids
    assert "unstructured-elements" in ids
    assert "surya-noisy-lines" in ids
    assert "olmocr-linearized-text" in ids
    assert "multi-consensus-marker-paddle" in ids
    assert "multi" in adapters


def test_build_default_benchmark_cases_can_filter_adapters():
    cases = build_default_benchmark_cases(["marker"], include_candidate_sets=False)

    assert cases
    assert {case.adapter for case in cases} == {"marker"}
    assert {case.kind for case in cases} == {"single_payload"}


def test_case_public_hides_payload_unless_requested():
    case = case_by_id(build_default_benchmark_cases(["marker"], include_candidate_sets=False), "marker-complete-renewal")

    public = case.public()
    expanded = case.public(include_payload=True)

    assert "payload" not in public
    assert "payload" in expanded
    assert public["expectation"]["allowed_levels"]


def test_noise_helpers_model_common_ocr_failures():
    noisy = apply_ocr_noise(BASE_MORTGAGE_TEXT, intensity=4)
    without_balance = remove_lines_containing(BASE_MORTGAGE_TEXT, ("balance",))
    altered = replace_line_value(BASE_MORTGAGE_TEXT, "Posted rate", "5.19%")

    assert "intrest" in noisy
    assert "differental" in noisy
    assert "balance" not in without_balance.lower()
    assert "Posted rate: 5.19%" in altered
    assert "Posted rate: 5.69%" not in altered


def test_marker_payload_benchmark_passes_complete_case():
    case = case_by_id(build_default_benchmark_cases(["marker"], include_candidate_sets=False), "marker-complete-renewal")
    result = evaluate_benchmark_case(case)

    assert result["provider"] == "adapter-benchmark-case-result-v15"
    assert result["status"] == "pass"
    assert result["level"] in {"reviewable", "needs_review"}
    assert result["quality"]["has_money"] is True
    assert result["quality"]["has_rate"] is True


def test_thin_marker_case_is_expected_to_block_on_missing_balance():
    case = case_by_id(build_default_benchmark_cases(["marker"], include_candidate_sets=False), "marker-thin-rates-only")
    result = evaluate_benchmark_case(case)

    assert result["status"] == "pass"
    assert result["level"] == "blocked"
    assert "action-field-balance" in result["action_ids"]
    assert any(check["id"] == "actions" and check["passed"] for check in result["checks"])


def test_low_confidence_paddle_case_requires_span_review():
    case = case_by_id(
        build_default_benchmark_cases(["paddleocr"], include_candidate_sets=False),
        "paddleocr-low-confidence-lines",
    )
    result = evaluate_benchmark_case(case)

    assert result["status"] == "pass"
    assert "action-review-low-confidence" in result["action_ids"]
    assert result["quality"]["low_confidence_span_ids"]


def test_multi_candidate_consensus_case_checks_reconciliation_status():
    case = case_by_id(build_default_benchmark_cases(), "multi-consensus-marker-paddle")
    result = evaluate_benchmark_case(case)

    assert result["status"] == "pass"
    assert result["workbench"]["evaluated_count"] == 2
    assert result["reconciliation_statuses"]["contract_rate"] == "consensus"
    assert any(check["id"] == "reconciliation-contract_rate" for check in result["checks"])


def test_multi_candidate_conflict_case_checks_posted_rate_disagreement():
    case = case_by_id(build_default_benchmark_cases(), "multi-conflict-posted-rate")
    result = evaluate_benchmark_case(case)

    assert result["status"] == "pass"
    assert result["workbench"]["evaluated_count"] == 2
    assert result["reconciliation_statuses"]["posted_rate"] == "conflict"


def test_evaluate_benchmark_case_rejects_unknown_case_kind():
    case = BenchmarkCase(
        id="bad-kind",
        title="Bad kind",
        objective="Exercise validation",
        kind="unknown",
        adapter="marker",
        payload=marker_payload(thin_rate_text()),
        expectation=BenchmarkExpectation(allowed_levels=("blocked",)),
    )

    with pytest.raises(AdapterBenchmarkError):
        evaluate_benchmark_case(case)


def test_summarize_benchmark_results_counts_pass_rate_and_coverage():
    case = case_by_id(build_default_benchmark_cases(["marker"], include_candidate_sets=False), "marker-thin-rates-only")
    result = evaluate_benchmark_case(case)
    summary = summarize_benchmark_results([result])

    assert summary["provider"] == "adapter-benchmark-summary-v15"
    assert summary["case_count"] == 1
    assert summary["passed_count"] == 1
    assert summary["pass_rate"] == 1.0
    assert summary["adapter_coverage"]["marker"] == 1
    assert summary["ready"] is True


def test_recommended_benchmark_actions_reports_failures():
    failed = {
        "status": "fail",
        "case": {"id": "case-1", "title": "Broken adapter"},
        "checks": [{"passed": False, "detail": "Missing required balance."}],
    }
    passed = {"status": "pass", "case": {"id": "case-2", "title": "Good adapter"}, "checks": []}

    failure_actions = recommended_benchmark_actions([failed])
    keep_actions = recommended_benchmark_actions([passed])

    assert failure_actions[0]["priority"] == "high"
    assert failure_actions[0]["case_id"] == "case-1"
    assert keep_actions[0]["id"] == "benchmark-action-keep-fixtures"


def test_run_adapter_benchmark_suite_returns_summary_results_and_actions():
    suite = run_adapter_benchmark_suite(["marker"], include_candidate_sets=False)

    assert suite["provider"] == "adapter-benchmark-suite-v15"
    assert suite["summary"]["case_count"] == 2
    assert suite["summary"]["passed_count"] == 2
    assert suite["results"]
    assert suite["actions"]
    assert suite["notice"]


def test_run_adapter_benchmark_suite_rejects_empty_filter():
    with pytest.raises(AdapterBenchmarkError):
        run_adapter_benchmark_suite(["not-real"], include_candidate_sets=False)


def test_candidate_case_can_be_constructed_from_custom_payloads():
    case = BenchmarkCase(
        id="custom-consensus",
        title="Custom consensus",
        objective="Two adapter candidates agree",
        kind="candidate_set",
        adapter="multi",
        payload={
            "candidates": [
                {"adapter": "marker", "payload": marker_payload()},
                {"adapter": "paddleocr", "payload": paddle_payload()},
            ]
        },
        expectation=BenchmarkExpectation(
            allowed_levels=("reviewable", "needs_review", "blocked"),
            required_reconciliation_statuses={"contract_rate": "consensus"},
        ),
    )
    result = evaluate_benchmark_case(case)

    assert result["status"] == "pass"
    assert result["reconciliation_statuses"]["contract_rate"] == "consensus"
