import pytest

from renewal.ocr.contract_intelligence import create_contract_brief
from renewal.ocr.dependency_adapters_v14 import (
    DependencyAdapterError,
    adapter_input_profiles,
    adapter_blockers,
    adapter_execution_steps,
    best_available_chain,
    build_adapter_readiness_report,
    build_dependency_adapter_plan_from_brief,
    create_adapter_readiness_report,
    dependency_install_groups,
    dependency_status,
    document_feature_signals,
    local_fallback_chain,
    normalized_input_contract,
    optional_dependency_registry,
    optional_requirements_lines,
    ranked_adapter_profiles,
    readiness_gates,
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


def brief(text=SAMPLE_TEXT, filename="renewal-contract.pdf"):
    return create_contract_brief(
        pages(text),
        filename=filename,
        question="Explain the penalty and contract discount",
    )


def test_optional_dependency_registry_records_best_github_references():
    registry = optional_dependency_registry()

    assert set(registry) == {"docling", "unstructured", "paddleocr", "surya", "marker", "olmocr"}
    assert registry["docling"].github == "https://github.com/docling-project/docling"
    assert registry["paddleocr"].version_hint == ">=3.7,<4"
    assert registry["olmocr"].install_group == "ocr_evaluation"
    assert all(not item.default_enabled for item in registry.values())
    assert all(item.why_optional for item in registry.values())


def test_optional_requirements_manifest_is_separate_from_base_runtime():
    lines = optional_requirements_lines(optional_dependency_registry())
    text = "\n".join(lines)

    assert "NOT required for the default app" in text
    assert "docling>=2.119,<3" in text
    assert "paddleocr>=3.7,<4" in text
    assert "marker-pdf>=2,<3" in text
    assert all("pytest" not in line for line in lines)


def test_dependency_status_never_imports_heavy_runtime_modules():
    status = dependency_status(optional_dependency_registry())

    assert set(status) == set(optional_dependency_registry())
    assert all(item["runtime_required"] is False for item in status.values())
    assert all("installed" in item for item in status.values())
    assert all("can_import" in item for item in status.values())


def test_adapter_profiles_describe_inputs_outputs_and_validation_checks():
    profiles = adapter_input_profiles()

    assert "docling_structured_pdf" in profiles
    assert "paddleocr_v6_structure" in profiles
    assert "olmocr_quality_eval" in profiles
    assert "pdf" in profiles["docling_structured_pdf"].accepts
    assert "page_images" in profiles["paddleocr_v6_structure"].required_inputs
    assert "quality_flags" in profiles["olmocr_quality_eval"].expected_outputs
    assert all(profile.validation_checks for profile in profiles.values())


def test_document_feature_signals_detect_contract_context_from_brief():
    signals = document_feature_signals(brief())

    assert signals["extension"] == "pdf"
    assert signals["is_pdf"] is True
    assert signals["has_rate_context"] is True
    assert signals["has_penalty_context"] is True
    assert signals["has_timeline_context"] is True
    assert signals["has_payment_context"] is True
    assert signals["field_count"] >= 8


def test_ranked_adapter_profiles_prioritize_structure_and_quality_for_pdf_contract():
    contract = brief()
    fake_status = {
        key: {"installed": False}
        for key in optional_dependency_registry()
    }
    ranked = ranked_adapter_profiles(contract, fake_status)
    keys = [item["profile_key"] for item in ranked]

    assert keys[0] in {"docling_structured_pdf", "marker_json_chunks", "unstructured_partition"}
    assert any(item["profile_key"] == "olmocr_quality_eval" for item in ranked)
    assert all(item["can_run_now"] is False for item in ranked)
    assert ranked[0]["score"] >= ranked[-1]["score"]
    assert ranked[0]["reasons"]


def test_ranked_adapter_profiles_marks_installed_profiles_as_runnable():
    contract = brief()
    fake_status = {
        key: {"installed": key == "docling"}
        for key in optional_dependency_registry()
    }
    ranked = ranked_adapter_profiles(contract, fake_status)
    docling = next(item for item in ranked if item["dependency_key"] == "docling")

    assert docling["installed"] is True
    assert docling["can_run_now"] is True
    assert "optional dependency is installed" in docling["reasons"]


def test_best_available_chain_uses_one_profile_per_dependency():
    contract = brief()
    fake_status = {key: {"installed": False} for key in optional_dependency_registry()}
    ranked = ranked_adapter_profiles(contract, fake_status)
    chain = best_available_chain(ranked, limit=4)

    assert 1 <= len(chain) <= 4
    assert len({item["dependency_key"] for item in chain}) == len(chain)
    assert all("fallback_profile" in item for item in chain)


def test_normalized_input_contract_maps_github_profile_to_local_evidence_schema():
    contract = brief()
    profile = adapter_input_profiles()["paddleocr_v6_structure"]
    input_contract = normalized_input_contract(profile, contract)

    assert input_contract["profile_key"] == "paddleocr_v6_structure"
    assert input_contract["dependency_key"] == "paddleocr"
    assert input_contract["privacy_controls"]["redact_identifiers_before_public_output"] is True
    assert "field:contract_rate" in input_contract["mortgage_targets"]["evidence_targets"]
    assert input_contract["output_mapping"]["text_lines"] == "ocr.pages[].text"


def test_install_groups_collect_optional_dependencies_by_runtime_shape():
    groups = dependency_install_groups(optional_dependency_registry())

    assert "document_structure" in groups
    assert "ocr_models" in groups
    assert groups["ocr_models"][0]["key"] == "paddleocr"
    assert all(group_items for group_items in groups.values())


def test_local_fallback_chain_stays_active_without_external_dependencies():
    chain = local_fallback_chain(brief())

    assert chain[0]["key"] == "existing_ocr_text_upload"
    assert any(item["key"] == "evidence_graph_contract_intelligence" for item in chain)
    assert all(item["active"] is True for item in chain)


def test_local_fallback_chain_adds_manual_review_when_fields_are_missing():
    thin = brief("Contract rate: 4.39%\nPosted rate: 5.69%", filename="thin.txt")
    chain = local_fallback_chain(thin)

    assert any(item["key"] == "manual_reviewer_correction" for item in chain)


def test_build_dependency_adapter_plan_combines_research_math_and_profiles():
    plan = build_dependency_adapter_plan_from_brief(brief())

    assert plan["provider"] == "optional-dependency-adapter-plan-v14"
    assert plan["policy"]["base_app_requires_optional_dependencies"] is False
    assert plan["policy"]["github_code_copied"] is False
    assert plan["dependency_status"]
    assert plan["install_groups"]
    assert plan["optional_requirements"]
    assert plan["ranked_profiles"]
    assert plan["recommended_chain"]
    assert plan["input_contracts"]
    assert plan["research_radar_summary"]["adapter_needs"]
    assert plan["math_confidence"]["human_review_required"] is True
    assert "ABCD-1234-5678" not in str(plan)


def test_build_dependency_adapter_plan_exposes_missing_field_signals():
    thin = brief("Contract rate: 4.39%\nPosted rate: 5.69%", filename="thin.pdf")
    plan = build_dependency_adapter_plan_from_brief(thin)

    assert plan["document_signals"]["has_required_missing"] is True
    assert "balance" in plan["document_signals"]["missing_required"]
    assert any(item["key"] == "manual_reviewer_correction" for item in plan["local_fallback_chain"])


def test_readiness_gates_explain_base_runtime_and_optional_dependency_review():
    plan = build_dependency_adapter_plan_from_brief(brief())
    gates = readiness_gates(plan)
    by_id = {gate["id"]: gate for gate in gates}

    assert by_id["base-runtime"]["status"] == "ready"
    assert by_id["dependency-review"]["status"] == "review_required"
    assert by_id["installed-adapters"]["status"] in {"ready", "not_installed"}
    assert "local_fallback_chain" in by_id["base-runtime"]["evidence"]


def test_readiness_gates_block_missing_required_fields():
    plan = build_dependency_adapter_plan_from_brief(
        brief("Contract rate: 4.39%\nPosted rate: 5.69%", filename="thin.pdf")
    )
    gates = readiness_gates(plan)
    missing = next(gate for gate in gates if gate["id"] == "missing-fields")

    assert missing["status"] == "blocked"
    assert "field:balance" in missing["evidence"]


def test_adapter_execution_steps_include_inputs_outputs_and_fallbacks():
    plan = build_dependency_adapter_plan_from_brief(brief())
    steps = adapter_execution_steps(plan)

    assert steps
    assert all(step["required_inputs"] for step in steps)
    assert all(step["expected_outputs"] for step in steps)
    assert all(step["validation_checks"] for step in steps)
    assert steps[0]["action"] in {"run_optional_adapter", "use_local_fallback_or_install_deliberately"}


def test_adapter_blockers_distinguish_high_missing_fields_from_low_optional_installs():
    plan = build_dependency_adapter_plan_from_brief(
        brief("Contract rate: 4.39%\nPosted rate: 5.69%", filename="thin.pdf")
    )
    blockers = adapter_blockers(plan)
    severities = {item["severity"] for item in blockers}

    assert "high" in severities
    assert any(item["id"] == "missing-fields" for item in blockers)
    assert any(item["id"].startswith("optional-") for item in blockers)


def test_build_adapter_readiness_report_summarizes_plan_for_operator():
    plan = build_dependency_adapter_plan_from_brief(brief())
    report = build_adapter_readiness_report(plan)

    assert report["provider"] == "optional-adapter-readiness-report-v14"
    assert report["ready_to_run_base_app"] is True
    assert report["can_prefill_without_manual_review"] is False
    assert report["gates"]
    assert report["execution_steps"]
    assert report["summary"]["recommended_profile_count"] >= 1
    assert report["operator_notes"]
    assert "ABCD-1234-5678" not in str(report)


def test_create_adapter_readiness_report_runs_from_pages():
    report = create_adapter_readiness_report(
        pages(),
        filename="renewal-contract.pdf",
        question="Which adapter is ready?",
    )

    assert report["provider"] == "optional-adapter-readiness-report-v14"
    assert report["summary"]["input_contract_count"] >= 1


def test_adapter_readiness_report_rejects_wrong_plan_provider():
    with pytest.raises(DependencyAdapterError):
        build_adapter_readiness_report({"provider": "old"})


def test_dependency_adapter_plan_rejects_non_v12_briefs():
    with pytest.raises(DependencyAdapterError):
        build_dependency_adapter_plan_from_brief({"provider": "old"})
