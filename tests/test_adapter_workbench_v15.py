import pytest

from renewal.ocr.adapter_quality_harness_v15 import evaluate_adapter_payload
from renewal.ocr.adapter_workbench_v15 import (
    AdapterWorkbenchError,
    build_workbench_report,
    compare_adapter_payloads,
    consensus_signals,
    merge_candidate_pages,
    rank_candidate_scores,
    score_evaluation,
)


MORTGAGE_TEXT = """
Mortgage date: 2022-03-01
Outstanding mortgage balance at renewal: $480,000.00
Contract rate: 4.39%
Posted rate: 5.69%
Contract discount: 1.30%
Renewal interest rate: 5.49%
Remaining amortization period: 240 months
Maturity date: 2027-03-01
Interest rate differential applies if discharged early.
The penalty may be the greater of three months interest or the interest rate differential.
"""


def marker_payload(text=MORTGAGE_TEXT):
    return {
        "provider": "marker",
        "markdown": text,
        "chunks": [{"page": 1, "text": "Penalty: interest rate differential", "type": "clause"}],
        "blocks": [{"page": 1, "type": "table", "rows": [["Balance", "$480,000.00"], ["Rate", "5.49%"]]}],
    }


def paddle_payload(text=MORTGAGE_TEXT):
    return {
        "provider": "paddleocr",
        "ocr_result": [
            [[[0, index * 10], [500, index * 10], [500, index * 10 + 8], [0, index * 10 + 8]], [line, 0.93]]
            for index, line in enumerate(text.splitlines(), 1)
            if line.strip()
        ],
    }


def weak_payload():
    return {"provider": "marker", "markdown": "Contract rate: 4.39%\nPosted rate: 5.69%"}


def candidates():
    return [
        {"adapter": "marker", "payload": marker_payload()},
        {"adapter": "paddleocr", "payload": paddle_payload()},
        {"adapter": "marker", "payload": weak_payload()},
    ]


def test_score_evaluation_adds_quality_reasons():
    evaluation = evaluate_adapter_payload(marker_payload(), "marker")
    score = score_evaluation(1, evaluation)

    assert score.adapter == "marker"
    assert score.score > 0
    assert score.has_money is True
    assert score.has_rate is True
    assert score.has_penalty_language is True
    assert score.reasons


def test_rank_candidate_scores_selects_highest_candidate():
    good = score_evaluation(1, evaluate_adapter_payload(marker_payload(), "marker"))
    weak = score_evaluation(2, evaluate_adapter_payload(weak_payload(), "marker"))
    ranked = rank_candidate_scores([weak, good])

    assert ranked[0].selected is True
    assert ranked[0].score >= ranked[1].score
    assert ranked[1].selected is False


def test_compare_adapter_payloads_scores_and_selects_best_candidate():
    workbench = compare_adapter_payloads(candidates())

    assert workbench["provider"] == "adapter-comparison-workbench-v15"
    assert workbench["candidate_count"] == 3
    assert workbench["evaluated_count"] == 3
    assert workbench["selected_candidate_id"]
    assert workbench["selected_adapter"] in {"marker", "paddleocr"}
    assert workbench["selected_ocr_pages"]
    assert any(item["selected"] for item in workbench["scores"])


def test_compare_adapter_payloads_records_errors_without_losing_good_candidates():
    workbench = compare_adapter_payloads(
        candidates() + [{"adapter": "unknown", "payload": {"bad": "shape"}}]
    )

    assert workbench["candidate_count"] == 4
    assert workbench["evaluated_count"] == 3
    assert workbench["error_count"] == 1
    assert workbench["errors"][0]["status"] == "failed"
    assert workbench["selected_ocr_pages"]


def test_compare_adapter_payloads_requires_candidates():
    with pytest.raises(AdapterWorkbenchError):
        compare_adapter_payloads([])


def test_consensus_signals_reports_strength_and_shared_features():
    workbench = compare_adapter_payloads(candidates())
    consensus = consensus_signals(workbench)

    assert consensus["provider"] == "adapter-consensus-v15"
    assert consensus["consensus"] in {"strong", "moderate", "weak", "blocked"}
    assert consensus["candidate_count"] == 3
    assert consensus["shared_features"]["money"] >= 1
    assert consensus["top_candidate_id"] == workbench["selected_candidate_id"]


def test_consensus_signals_handles_no_scores():
    consensus = consensus_signals({"scores": []})
    assert consensus["consensus"] == "none"


def test_merge_candidate_pages_returns_selected_pages():
    workbench = compare_adapter_payloads(candidates())
    pages = merge_candidate_pages(workbench)

    assert pages
    assert pages[0]["text"]


def test_build_workbench_report_combines_workbench_consensus_and_pages():
    report = build_workbench_report(candidates())

    assert report["provider"] == "adapter-workbench-report-v15"
    assert report["workbench"]["provider"] == "adapter-comparison-workbench-v15"
    assert report["consensus"]["provider"] == "adapter-consensus-v15"
    assert report["merged_pages"]
    assert isinstance(report["ready_for_contract_pipeline"], bool)


def test_build_workbench_report_can_flag_weak_candidates():
    report = build_workbench_report([{"adapter": "marker", "payload": weak_payload()}])

    assert report["workbench"]["evaluated_count"] == 1
    assert report["workbench"]["scores"][0]["level"] == "blocked"
    assert report["ready_for_contract_pipeline"] is False
