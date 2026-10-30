import pytest

from renewal.ocr.contract_intelligence import create_contract_brief
from renewal.ocr.contract_math_v13 import build_contract_math_audit_from_brief
from renewal.ocr.research_radar_v13 import (
    ResearchRadarError,
    build_research_radar_from_brief,
    concept_summary,
    in_house_adapter_tasks,
    infer_adapter_needs,
    local_capability_inventory,
    research_source_map,
    research_sources,
    score_sources_for_needs,
)


SAMPLE_TEXT = """
Maple Bank Mortgage Renewal Agreement
Mortgage number: ABCD-1234-5678
Mortgage date: 2022-03-01
Outstanding mortgage balance at renewal: $480,000.00
Current interest rate: 4.39%
Contract rate: 4.39%
Posted rate: 5.69%
Contract discount: 1.30%
Renewal interest rate: 5.49%
Renewal term: 60 months
Remaining amortization period: 240 months
Maturity date: 2027-03-01
Payment amount: $3,285.00
Payment frequency: monthly
Interest rate differential applies if discharged early.
The penalty may be the greater of three months interest or the interest rate differential.
Prepayment privilege: 20% lump sum each year.
Offer expires: 2027-02-15.
"""


def pages(text=SAMPLE_TEXT):
    return [{"page_number": 1, "text": text, "mean_confidence": 0.94}]


def brief(text=SAMPLE_TEXT):
    return create_contract_brief(
        pages(text),
        filename="renewal-contract.txt",
        question="Explain my penalty and contract discount",
    )


def test_research_source_map_documents_web_and_github_references_without_dependencies():
    source_map = research_source_map()
    keys = {source["key"] for source in source_map["sources"]}

    assert source_map["provider"] == "contract-research-radar-v13"
    assert source_map["verified_date"] == "2026-10-13"
    assert source_map["runtime_dependency_count"] == 0
    assert {"docling", "unstructured", "paddleocr", "olmocr", "marker", "surya", "fcac"} <= keys
    assert source_map["policy"]["imports_external_projects"] is False
    assert source_map["policy"]["downloads_models"] is False


def test_research_sources_keep_github_as_reference_only():
    sources = research_sources()
    assert sources["docling"].repository == "https://github.com/docling-project/docling"
    assert sources["paddleocr"].repository == "https://github.com/PaddlePaddle/PaddleOCR"
    assert sources["olmocr"].repository == "https://github.com/allenai/olmocr"
    assert sources["marker"].repository == "https://github.com/datalab-to/marker"
    assert sources["fcac"].repository is None
    assert all(source.dependency_policy == "reference_only_no_runtime_import" for source in sources.values())


def test_infer_adapter_needs_finds_rate_penalty_timeline_and_payment_work():
    contract = brief()
    math_audit = build_contract_math_audit_from_brief(contract)
    needs = infer_adapter_needs(contract, math_audit)
    keys = [need["key"] for need in needs]

    assert keys[:3] == ["rate_context_reasoning", "penalty_language_review", "timeline_validation"]
    assert "payment_component_separation" in keys
    assert all(need["weight"] > 0 for need in needs)
    assert any("field:contract_rate" in need["evidence"] for need in needs)


def test_infer_adapter_needs_prioritizes_missing_required_field_recovery():
    thin = brief("Contract rate: 4.39%\nPosted rate: 5.69%")
    math_audit = build_contract_math_audit_from_brief(thin)
    needs = infer_adapter_needs(thin, math_audit)

    assert needs[0]["key"] == "required_field_recovery"
    assert needs[0]["weight"] == 95
    assert "field:balance" in needs[0]["evidence"]
    assert any(need["key"] == "math_input_completion" for need in needs)


def test_score_sources_for_needs_ranks_canadian_guidance_for_penalty_context():
    contract = brief()
    needs = infer_adapter_needs(contract, build_contract_math_audit_from_brief(contract))
    scored = score_sources_for_needs(needs)
    by_key = {item["source"]["key"]: item for item in scored}

    assert scored[0]["score"] >= scored[-1]["score"]
    assert by_key["fcac"]["score"] > 0
    assert any(match["need"] == "penalty_language_review" for match in by_key["fcac"]["matched_needs"])
    assert by_key["docling"]["recommendation"] == "reference_for_local_design"
    assert by_key["paddleocr"]["source"]["dependency_policy"] == "reference_only_no_runtime_import"


def test_in_house_adapter_tasks_are_local_and_acceptance_testable():
    contract = brief()
    needs = infer_adapter_needs(contract, build_contract_math_audit_from_brief(contract))
    tasks = in_house_adapter_tasks(needs)
    by_id = {task["id"]: task for task in tasks}

    assert "adapter-rate-context" in by_id
    assert "adapter-penalty-review" in by_id
    assert "adapter-timeline-validation" in by_id
    assert by_id["adapter-penalty-review"]["target_module"].endswith("contract_math_v13.py")
    assert all(task["acceptance_checks"] for task in tasks)
    assert all(task["no_dependency_reason"] for task in tasks)
    assert any("local" in task["no_dependency_reason"] for task in tasks)


def test_local_capability_inventory_lists_v13_modules():
    inventory = local_capability_inventory()
    keys = {item["key"] for item in inventory["capabilities"]}

    assert inventory["runtime_dependency_count"] == 0
    assert "contract_math_audit" in keys
    assert "research_radar" in keys
    assert all(item["status"] == "implemented" for item in inventory["capabilities"])


def test_concept_summary_explains_own_code_over_external_dependencies():
    needs = infer_adapter_needs(brief())
    summary = concept_summary(needs)

    assert "public GitHub ecosystem" in summary["headline"]
    assert any("own code" in line for line in summary["plain_language"])
    assert "rate_context_reasoning" in summary["detected_need_keys"]


def test_build_research_radar_from_brief_combines_math_playbook_and_sources():
    radar = build_research_radar_from_brief(brief())

    assert radar["provider"] == "no-dependency-contract-research-radar-v13"
    assert radar["dependency_policy"]["new_pip_dependencies"] == []
    assert radar["dependency_policy"]["github_code_copied"] is False
    assert radar["math_audit"]["provider"] == "canadian-contract-math-audit-v13"
    assert radar["playbook_summary"]["task_count"] >= 1
    assert radar["adapter_needs"]
    assert radar["source_scores"]
    assert radar["in_house_adapter_tasks"]
    assert "ABCD-1234-5678" not in str(radar)


def test_research_radar_stays_useful_for_thin_documents():
    thin = build_research_radar_from_brief(brief("Contract rate: 4.39%\nPosted rate: 5.69%"))
    need_keys = [need["key"] for need in thin["adapter_needs"]]
    task_ids = {task["id"] for task in thin["in_house_adapter_tasks"]}

    assert need_keys[0] == "required_field_recovery"
    assert "adapter-required-field-recovery" in task_ids
    assert thin["playbook_summary"]["critical_task_count"] >= 1
    assert thin["math_audit"]["confidence"]["level"] == "low"


def test_build_research_radar_rejects_non_v12_briefs():
    with pytest.raises(ResearchRadarError):
        build_research_radar_from_brief({"provider": "old"})
