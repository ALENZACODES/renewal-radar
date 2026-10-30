"""V14 optional dependency and adapter input planning.

This module "builds in" the best researched OCR/document-intelligence
dependencies without making the base application depend on heavyweight external
projects. It records optional packages, checks whether they are installed,
normalizes the inputs each adapter would need, and chooses a safe adapter chain
for mortgage-contract review.
"""
from __future__ import annotations

import importlib.metadata
import importlib.util
from dataclasses import asdict, dataclass
from typing import Any

from .contract_intelligence import create_contract_brief
from .contract_math_v13 import build_contract_math_audit_from_brief
from .research_radar_v13 import build_research_radar_from_brief


class DependencyAdapterError(ValueError):
    """The dependency adapter plan could not be generated."""


@dataclass(frozen=True)
class OptionalDependency:
    key: str
    package: str
    import_name: str
    version_hint: str
    license_or_access: str
    github: str
    documentation: str
    role: str
    best_for: tuple[str, ...]
    latest_signal: str
    install_group: str
    default_enabled: bool
    why_optional: str

    def public(self) -> dict:
        data = asdict(self)
        data["best_for"] = list(self.best_for)
        return data


@dataclass(frozen=True)
class AdapterInputProfile:
    key: str
    label: str
    dependency_key: str
    accepts: tuple[str, ...]
    preferred_for: tuple[str, ...]
    default_options: dict[str, Any]
    required_inputs: tuple[str, ...]
    expected_outputs: tuple[str, ...]
    validation_checks: tuple[str, ...]
    github_influence: str
    fallback_profile: str

    def public(self) -> dict:
        data = asdict(self)
        data["accepts"] = list(self.accepts)
        data["preferred_for"] = list(self.preferred_for)
        data["required_inputs"] = list(self.required_inputs)
        data["expected_outputs"] = list(self.expected_outputs)
        data["validation_checks"] = list(self.validation_checks)
        return data


@dataclass(frozen=True)
class AdapterScore:
    profile_key: str
    dependency_key: str
    score: int
    reasons: tuple[str, ...]
    installed: bool
    can_run_now: bool

    def public(self) -> dict:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data


def optional_dependency_registry() -> dict[str, OptionalDependency]:
    return {
        "docling": OptionalDependency(
            key="docling",
            package="docling",
            import_name="docling",
            version_hint=">=2.119,<3",
            license_or_access="MIT open source; verify transitive model licenses before deployment",
            github="https://github.com/docling-project/docling",
            documentation="https://docling-project.github.io/docling/",
            role="structured document conversion",
            best_for=(
                "PDF/Office conversion",
                "layout and reading order",
                "tables and formulas",
                "structured JSON-style document output",
            ),
            latest_signal="Docling documents OCR, table structure, formulas, reading order and structured conversion for complex documents.",
            install_group="document_structure",
            default_enabled=False,
            why_optional="Strong structure parser, but too large to require for every Renewal Radar install.",
        ),
        "unstructured": OptionalDependency(
            key="unstructured",
            package="unstructured",
            import_name="unstructured",
            version_hint=">=0.27,<1",
            license_or_access="Open-source package with separate optional extras",
            github="https://github.com/Unstructured-IO/unstructured",
            documentation="https://docs.unstructured.io/",
            role="document partitioning",
            best_for=(
                "chunking",
                "element partitioning",
                "HTML/DOCX/PDF ingestion",
                "lists and table preservation",
            ),
            latest_signal="GitHub releases continue to ship parser and partitioning fixes for multiple document types.",
            install_group="document_partitioning",
            default_enabled=False,
            why_optional="Useful adapter target, but installation extras vary by document type.",
        ),
        "paddleocr": OptionalDependency(
            key="paddleocr",
            package="paddleocr",
            import_name="paddleocr",
            version_hint=">=3.7,<4",
            license_or_access="Apache-2.0 project; model terms should still be reviewed",
            github="https://github.com/PaddlePaddle/PaddleOCR",
            documentation="https://paddleocr.dev/",
            role="OCR and document parsing",
            best_for=(
                "multilingual OCR",
                "PP-OCRv6 style recognition",
                "PP-Structure style parsing",
                "browser/edge direction via PaddleOCR.js",
            ),
            latest_signal="PaddleOCR documentation describes 3.7-era pipelines including PP-OCRv6, PP-StructureV3 and PaddleOCR-VL.",
            install_group="ocr_models",
            default_enabled=False,
            why_optional="High-value OCR engine, but model/runtime footprint should be explicit.",
        ),
        "surya": OptionalDependency(
            key="surya",
            package="surya-ocr",
            import_name="surya",
            version_hint=">=0.22,<1",
            license_or_access="Project/model license must be checked for production use",
            github="https://github.com/LPAI-Org/Surya",
            documentation="https://github.com/LPAI-Org/Surya",
            role="OCR, layout and line detection",
            best_for=(
                "line detection",
                "layout blocks",
                "OCR on image-heavy pages",
                "language-aware page processing",
            ),
            latest_signal="Surya is commonly referenced for layout analysis, line detection and OCR across many languages.",
            install_group="ocr_layout",
            default_enabled=False,
            why_optional="Good future line-box adapter, but not needed for text-only OCR uploads.",
        ),
        "marker": OptionalDependency(
            key="marker",
            package="marker-pdf",
            import_name="marker",
            version_hint=">=2,<3",
            license_or_access="Review package/model license before commercial deployment",
            github="https://github.com/datalab-to/marker",
            documentation="https://github.com/datalab-to/marker",
            role="PDF/document to Markdown, JSON, chunks and HTML",
            best_for=(
                "Markdown conversion",
                "JSON conversion",
                "document chunks",
                "force-OCR conversion path",
            ),
            latest_signal="Marker documents conversion to Markdown, JSON, chunks and HTML with OCR and optional LLM-assisted paths.",
            install_group="document_conversion",
            default_enabled=False,
            why_optional="Useful conversion target, but optional LLM/model paths should remain deliberate.",
        ),
        "olmocr": OptionalDependency(
            key="olmocr",
            package="olmocr",
            import_name="olmocr",
            version_hint=">=0.4,<1",
            license_or_access="Research toolkit; verify model and deployment terms",
            github="https://github.com/allenai/olmocr",
            documentation="https://olmocr.allenai.org/",
            role="PDF linearization and OCR evaluation",
            best_for=(
                "PDF-to-linear-text evaluation",
                "OCR quality benchmarks",
                "unit-test style OCR checks",
                "LLM-ready document text",
            ),
            latest_signal="GitHub releases show continuing v0.4.x activity and the project focuses on linearizing PDFs for LLM datasets/training.",
            install_group="ocr_evaluation",
            default_enabled=False,
            why_optional="Excellent evaluation influence, but not required for deterministic mortgage review.",
        ),
    }


def adapter_input_profiles() -> dict[str, AdapterInputProfile]:
    return {
        "docling_structured_pdf": AdapterInputProfile(
            key="docling_structured_pdf",
            label="Docling structured PDF conversion",
            dependency_key="docling",
            accepts=("pdf", "docx", "pptx", "xlsx", "html", "image"),
            preferred_for=("layout", "tables", "formulas", "reading_order", "mixed_native_and_scanned_pdf"),
            default_options={
                "do_ocr": True,
                "do_table_structure": True,
                "table_structure_mode": "accurate",
                "force_full_page_ocr": False,
                "export_format": "json",
            },
            required_inputs=("file_path_or_bytes", "document_type", "privacy_mode"),
            expected_outputs=("pages", "tables", "sections", "reading_order", "text_spans"),
            validation_checks=(
                "page count matches source",
                "tables preserve row/column order",
                "rate and date labels stay near extracted values",
                "raw text is redacted before public export",
            ),
            github_influence="Docling model catalog and pipeline options emphasize structured conversion, OCR, tables and reading order.",
            fallback_profile="text_only_contract_understanding",
        ),
        "unstructured_partition": AdapterInputProfile(
            key="unstructured_partition",
            label="Unstructured element partition",
            dependency_key="unstructured",
            accepts=("pdf", "docx", "html", "txt"),
            preferred_for=("chunking", "lists", "tables", "html_docx", "long_contracts"),
            default_options={
                "strategy": "hi_res",
                "include_page_breaks": True,
                "infer_table_structure": True,
                "chunking_strategy": "by_title",
            },
            required_inputs=("file_path_or_bytes", "document_type"),
            expected_outputs=("elements", "metadata", "chunks", "tables"),
            validation_checks=(
                "element order is stable",
                "list bullets are preserved",
                "tables are not flattened into unrelated text",
                "chunks retain page and section metadata",
            ),
            github_influence="Unstructured release stream centers on robust partitioning and document element handling.",
            fallback_profile="text_only_sectioning",
        ),
        "paddleocr_v6_structure": AdapterInputProfile(
            key="paddleocr_v6_structure",
            label="PaddleOCR OCR and structure pass",
            dependency_key="paddleocr",
            accepts=("image", "scanned_pdf", "pdf_page_image"),
            preferred_for=("ocr", "multilingual", "edge_or_browser_future", "tables", "forms"),
            default_options={
                "pipeline": "PP-OCRv6_or_PP-StructureV3",
                "use_doc_orientation_classify": True,
                "use_doc_unwarping": True,
                "use_textline_orientation": True,
                "languages": ["en"],
                "output_format": "json",
            },
            required_inputs=("page_images", "languages", "dpi"),
            expected_outputs=("text_lines", "confidence", "boxes", "table_blocks"),
            validation_checks=(
                "low-confidence lines are routed to review",
                "currency values keep decimal precision",
                "percent rates retain percent signs or numeric rate metadata",
                "line boxes can map back to page evidence",
            ),
            github_influence="PaddleOCR 3.x/PP-OCRv6 direction highlights OCR pipelines, structure parsing and browser/edge deployment.",
            fallback_profile="existing_ocr_text_upload",
        ),
        "surya_layout_lines": AdapterInputProfile(
            key="surya_layout_lines",
            label="Surya layout and line detection",
            dependency_key="surya",
            accepts=("image", "pdf_page_image", "scanned_pdf"),
            preferred_for=("line_detection", "layout", "language_aware_ocr", "rotated_scans"),
            default_options={
                "task": "layout_and_line_detection",
                "detect_tables": True,
                "return_boxes": True,
                "languages": ["en"],
            },
            required_inputs=("page_images", "languages"),
            expected_outputs=("layout_blocks", "line_boxes", "text_lines", "confidence"),
            validation_checks=(
                "line order matches visual reading order",
                "rotated pages are flagged",
                "rate labels and numeric values stay in the same block",
                "boxes remain page-local",
            ),
            github_influence="Surya is used as a reference for line detection, layout blocks and language-aware OCR.",
            fallback_profile="existing_ocr_text_upload",
        ),
        "marker_json_chunks": AdapterInputProfile(
            key="marker_json_chunks",
            label="Marker JSON and chunk conversion",
            dependency_key="marker",
            accepts=("pdf", "image", "docx"),
            preferred_for=("markdown", "json", "chunks", "force_ocr", "rag_ready_output"),
            default_options={
                "output_format": "json",
                "force_ocr": "auto",
                "paginate_output": True,
                "extract_images": False,
                "use_llm": False,
            },
            required_inputs=("file_path_or_bytes", "document_type"),
            expected_outputs=("markdown", "json", "chunks", "page_map"),
            validation_checks=(
                "chunks include page references",
                "tables are represented as structured data when possible",
                "LLM-assisted mode stays disabled unless explicitly configured",
                "output can be converted into Renewal Radar evidence nodes",
            ),
            github_influence="Marker's public interface centers on Markdown, JSON, chunks and HTML conversion with force-OCR options.",
            fallback_profile="text_only_contract_understanding",
        ),
        "olmocr_quality_eval": AdapterInputProfile(
            key="olmocr_quality_eval",
            label="olmOCR quality evaluation",
            dependency_key="olmocr",
            accepts=("pdf", "linearized_text", "markdown"),
            preferred_for=("evaluation", "quality_tests", "llm_ready_text", "benchmarks"),
            default_options={
                "mode": "evaluate_or_linearize",
                "require_page_anchors": True,
                "emit_quality_flags": True,
            },
            required_inputs=("pdf_or_text", "expected_fields"),
            expected_outputs=("linearized_text", "quality_flags", "missing_expected_items"),
            validation_checks=(
                "expected mortgage fields appear or fail with missing-field flags",
                "tables and formulas are checked by assertions",
                "evidence remains page-traceable",
                "quality flags feed review tasks",
            ),
            github_influence="olmOCR's unit-test reward and benchmark posture is a good fit for document quality gates.",
            fallback_profile="local_quality_checks",
        ),
    }


def dependency_status(registry: dict[str, OptionalDependency] | None = None) -> dict[str, dict]:
    registry = registry or optional_dependency_registry()
    status = {}
    for key, dependency in registry.items():
        found = importlib.util.find_spec(dependency.import_name) is not None
        version = None
        if found:
            try:
                version = importlib.metadata.version(dependency.package)
            except importlib.metadata.PackageNotFoundError:
                version = "installed_unknown_version"
        status[key] = {
            **dependency.public(),
            "installed": found,
            "installed_version": version,
            "can_import": found,
            "runtime_required": False,
        }
    return status


def document_feature_signals(brief: dict) -> dict:
    filename = str(brief.get("filename") or "").lower()
    graph_summary = brief.get("evidence_graph", {}).get("summary", {})
    fields = set(brief.get("extraction", {}).get("fields", {}))
    risks = {risk.get("id") for risk in brief.get("risk_assessment", {}).get("risks", [])}
    missing_required = brief.get("readiness", {}).get("missing_required", [])
    review_questions = brief.get("review_questions", [])
    text_density = brief.get("understanding_score", {}).get("score", 0)
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "txt"
    return {
        "extension": ext,
        "is_pdf": ext == "pdf",
        "is_image": ext in {"png", "jpg", "jpeg", "tif", "tiff", "webp"},
        "is_text_upload": ext in {"txt", "text", "ocr"},
        "has_rate_context": bool(graph_summary.get("has_rate_context")),
        "has_penalty_context": bool(graph_summary.get("has_penalty_context")),
        "has_timeline_context": bool(graph_summary.get("has_timeline_context")),
        "has_required_missing": bool(missing_required),
        "missing_required": list(missing_required),
        "has_tables_or_lists": any("table" in str(item).lower() or "list" in str(item).lower() for item in review_questions),
        "has_payment_context": "payment_amount" in fields or "frequency" in fields,
        "has_discount_mismatch": "discount-math-review" in risks,
        "has_ird_language": "ird-language-found" in risks,
        "field_count": len(fields),
        "understanding_score": text_density,
    }


def _score_profile(profile: AdapterInputProfile, signals: dict, installed: bool) -> AdapterScore:
    score = 0
    reasons: list[str] = []
    preferred = set(profile.preferred_for)
    accepts = set(profile.accepts)

    if signals["is_pdf"] and "pdf" in accepts:
        score += 20
        reasons.append("document extension can be handled as PDF")
    if signals["is_image"] and accepts & {"image", "pdf_page_image"}:
        score += 22
        reasons.append("image/scanned input can use OCR/layout profile")
    if signals["has_required_missing"] and preferred & {"ocr", "layout", "tables", "forms", "chunking"}:
        score += 20
        reasons.append("missing required fields may need stronger parsing")
    if signals["has_rate_context"] and preferred & {"layout", "chunking", "json", "tables"}:
        score += 13
        reasons.append("rate labels benefit from structure-aware evidence")
    if signals["has_penalty_context"] and preferred & {"quality_tests", "llm_ready_text", "chunking"}:
        score += 14
        reasons.append("penalty clauses benefit from quality checks and stable chunks")
    if signals["has_timeline_context"] and preferred & {"reading_order", "quality_tests", "json"}:
        score += 10
        reasons.append("date/term reasoning benefits from ordered structured output")
    if signals["has_tables_or_lists"] and preferred & {"tables", "lists", "json"}:
        score += 18
        reasons.append("tables/lists are visible review concerns")
    if signals["has_payment_context"] and preferred & {"tables", "forms", "json"}:
        score += 12
        reasons.append("payment components often need table/form preservation")
    if signals["has_discount_mismatch"] and preferred & {"quality_tests", "tables", "json"}:
        score += 16
        reasons.append("discount mismatch should be rechecked with structured evidence")
    if installed:
        score += 8
        reasons.append("optional dependency is installed")
    if not reasons:
        reasons.append("profile remains available as a future optional adapter")
    return AdapterScore(
        profile_key=profile.key,
        dependency_key=profile.dependency_key,
        score=score,
        reasons=tuple(reasons),
        installed=installed,
        can_run_now=installed,
    )


def ranked_adapter_profiles(brief: dict, installed_status: dict[str, dict] | None = None) -> list[dict]:
    installed_status = installed_status or dependency_status()
    signals = document_feature_signals(brief)
    profiles = adapter_input_profiles()
    scored = []
    for profile in profiles.values():
        installed = bool(installed_status.get(profile.dependency_key, {}).get("installed"))
        score = _score_profile(profile, signals, installed)
        scored.append({**score.public(), "profile": profile.public()})
    return sorted(scored, key=lambda item: (-item["score"], item["profile_key"]))


def best_available_chain(ranked: list[dict], *, limit: int = 4) -> list[dict]:
    chain = []
    used_dependencies = set()
    for item in ranked:
        dependency = item["dependency_key"]
        if dependency in used_dependencies:
            continue
        used_dependencies.add(dependency)
        chain.append(
            {
                "profile_key": item["profile_key"],
                "dependency_key": dependency,
                "score": item["score"],
                "can_run_now": item["can_run_now"],
                "fallback_profile": item["profile"]["fallback_profile"],
                "why": item["reasons"],
            }
        )
        if len(chain) >= limit:
            break
    return chain


def normalized_input_contract(profile: AdapterInputProfile, brief: dict) -> dict:
    signals = document_feature_signals(brief)
    required_fields = brief.get("readiness", {}).get("missing_required", [])
    evidence_targets = [
        "field:balance",
        "field:contract_rate",
        "field:posted_rate",
        "field:contract_discount",
        "field:offered_rate",
        "field:maturity_date",
        "clause:interest_rate_differential",
        "clause:three_month_interest_penalty",
    ]
    return {
        "profile_key": profile.key,
        "dependency_key": profile.dependency_key,
        "accepted_inputs": list(profile.accepts),
        "required_inputs": list(profile.required_inputs),
        "default_options": profile.default_options,
        "expected_outputs": list(profile.expected_outputs),
        "validation_checks": list(profile.validation_checks),
        "document_signals": signals,
        "mortgage_targets": {
            "required_missing": required_fields,
            "evidence_targets": evidence_targets,
            "rate_fields": ["contract_rate", "posted_rate", "contract_discount", "offered_rate", "current_rate"],
            "date_fields": ["mortgage_start_date", "maturity_date", "term_months"],
            "penalty_clauses": ["interest_rate_differential", "three_month_interest_penalty"],
        },
        "privacy_controls": {
            "redact_identifiers_before_public_output": True,
            "do_not_store_raw_ocr_in_public_response": True,
            "review_required_before_prefill": True,
        },
        "output_mapping": {
            "text_lines": "ocr.pages[].text",
            "tables": "understanding.sections or future table evidence nodes",
            "layout_blocks": "evidence_graph.nodes with page/box metadata",
            "quality_flags": "review_questions and risk_assessment.risks",
            "chunks": "sections and clause candidates",
        },
    }


def optional_requirements_lines(registry: dict[str, OptionalDependency] | None = None) -> list[str]:
    registry = registry or optional_dependency_registry()
    lines = [
        "# Optional OCR/document-intelligence adapters for Renewal Radar.",
        "# These are NOT required for the default app or tests.",
        "# Install deliberately after reviewing model, license, hardware and privacy posture.",
    ]
    for dependency in registry.values():
        lines.append(f"{dependency.package}{dependency.version_hint}  # {dependency.key}: {dependency.role}")
    return lines


def dependency_install_groups(registry: dict[str, OptionalDependency] | None = None) -> dict[str, list[dict]]:
    registry = registry or optional_dependency_registry()
    groups: dict[str, list[dict]] = {}
    for dependency in registry.values():
        groups.setdefault(dependency.install_group, []).append(
            {
                "key": dependency.key,
                "package": dependency.package,
                "version_hint": dependency.version_hint,
                "default_enabled": dependency.default_enabled,
                "why_optional": dependency.why_optional,
            }
        )
    return groups


def local_fallback_chain(brief: dict) -> list[dict]:
    signals = document_feature_signals(brief)
    chain = [
        {
            "key": "existing_ocr_text_upload",
            "module": "backend/renewal/ocr/fields.py",
            "reason": "Use already supplied OCR text and confidence scores.",
            "active": True,
        },
        {
            "key": "text_only_contract_understanding",
            "module": "backend/renewal/ocr/document_understanding.py",
            "reason": "Classify document type, clauses, sections and Canadian mortgage terms from text.",
            "active": True,
        },
        {
            "key": "evidence_graph_contract_intelligence",
            "module": "backend/renewal/ocr/contract_intelligence.py",
            "reason": "Attach answers, risks and lender questions to deterministic evidence IDs.",
            "active": True,
        },
        {
            "key": "math_and_packet_review",
            "module": "backend/renewal/ocr/contract_math_v13.py + contract_packet_v13.py",
            "reason": "Create formula walkthroughs, disclosure prompts and safe lender packets.",
            "active": True,
        },
    ]
    if signals["has_required_missing"]:
        chain.append(
            {
                "key": "manual_reviewer_correction",
                "module": "backend/renewal/ocr/review_sessions.py",
                "reason": "Missing required fields must be corrected or confirmed by a reviewer.",
                "active": True,
            }
        )
    return chain


def build_dependency_adapter_plan_from_brief(brief: dict) -> dict:
    if not isinstance(brief, dict) or brief.get("provider") != "deterministic-contract-intelligence-v12":
        raise DependencyAdapterError("Expected a V12 contract-intelligence brief")
    registry = optional_dependency_registry()
    status = dependency_status(registry)
    ranked = ranked_adapter_profiles(brief, status)
    profiles = adapter_input_profiles()
    contracts = [
        normalized_input_contract(profiles[item["profile_key"]], brief)
        for item in ranked[:5]
    ]
    radar = build_research_radar_from_brief(brief)
    math_audit = build_contract_math_audit_from_brief(brief)
    return {
        "provider": "optional-dependency-adapter-plan-v14",
        "filename": brief.get("filename"),
        "verified_date": "2026-10-13",
        "policy": {
            "base_app_requires_optional_dependencies": False,
            "optional_dependencies_are_built_in_as_profiles": True,
            "imports_are_detected_not_forced": True,
            "github_code_copied": False,
            "install_only_with_user_approval": True,
        },
        "document_signals": document_feature_signals(brief),
        "dependency_status": status,
        "install_groups": dependency_install_groups(registry),
        "optional_requirements": optional_requirements_lines(registry),
        "ranked_profiles": ranked,
        "recommended_chain": best_available_chain(ranked),
        "input_contracts": contracts,
        "local_fallback_chain": local_fallback_chain(brief),
        "research_radar_summary": {
            "provider": radar.get("provider"),
            "adapter_needs": [need["key"] for need in radar.get("adapter_needs", [])],
            "top_sources": [item["source"]["key"] for item in radar.get("source_scores", [])[:3]],
        },
        "math_confidence": math_audit.get("confidence"),
        "notice": "Optional adapters are planned and detectable; the delivered app remains runnable with its base dependencies.",
    }


def readiness_gates(plan: dict) -> list[dict]:
    gates = [
        {
            "id": "base-runtime",
            "status": "ready",
            "title": "Base Renewal Radar runtime works without optional OCR engines",
            "detail": "The local OCR text, contract intelligence, math audit and lender packet path remains active.",
            "evidence": ["local_fallback_chain"],
        },
        {
            "id": "dependency-review",
            "status": "review_required",
            "title": "Optional dependency license and model review",
            "detail": "Install optional OCR engines only after license, model, privacy and hardware review.",
            "evidence": ["optional_requirements", "dependency_status"],
        },
    ]
    if plan.get("document_signals", {}).get("has_required_missing"):
        gates.append(
            {
                "id": "missing-fields",
                "status": "blocked",
                "title": "Required mortgage fields are missing",
                "detail": "A stronger parser may help, but manual review remains required before prefill.",
                "evidence": [f"field:{key}" for key in plan.get("document_signals", {}).get("missing_required", [])],
            }
        )
    installed = [
        key for key, item in plan.get("dependency_status", {}).items()
        if item.get("installed")
    ]
    gates.append(
        {
            "id": "installed-adapters",
            "status": "ready" if installed else "not_installed",
            "title": "Optional adapter import check",
            "detail": (
                "At least one optional adapter package is installed."
                if installed
                else "No optional OCR adapter package is currently importable; local fallback remains active."
            ),
            "evidence": installed,
        }
    )
    return gates


def adapter_execution_steps(plan: dict) -> list[dict]:
    steps = []
    for index, item in enumerate(plan.get("recommended_chain", []), 1):
        contract = next(
            (entry for entry in plan.get("input_contracts", [])
             if entry.get("profile_key") == item.get("profile_key")),
            None,
        )
        steps.append(
            {
                "id": f"adapter-step-{index:03d}",
                "profile_key": item.get("profile_key"),
                "dependency_key": item.get("dependency_key"),
                "can_run_now": item.get("can_run_now"),
                "action": (
                    "run_optional_adapter"
                    if item.get("can_run_now")
                    else "use_local_fallback_or_install_deliberately"
                ),
                "fallback_profile": item.get("fallback_profile"),
                "required_inputs": contract.get("required_inputs", []) if contract else [],
                "expected_outputs": contract.get("expected_outputs", []) if contract else [],
                "validation_checks": contract.get("validation_checks", []) if contract else [],
                "why": item.get("why", []),
            }
        )
    if not steps:
        steps.append(
            {
                "id": "adapter-step-001",
                "profile_key": "local_fallback",
                "dependency_key": "base_app",
                "can_run_now": True,
                "action": "run_local_fallback",
                "fallback_profile": None,
                "required_inputs": ["ocr_text_pages"],
                "expected_outputs": ["fields", "brief", "math_audit", "lender_packet"],
                "validation_checks": ["manual review remains required"],
                "why": ["No optional adapter profile was recommended."],
            }
        )
    return steps


def adapter_blockers(plan: dict) -> list[dict]:
    blockers = []
    for gate in readiness_gates(plan):
        if gate["status"] == "blocked":
            blockers.append(
                {
                    "id": gate["id"],
                    "severity": "high",
                    "title": gate["title"],
                    "detail": gate["detail"],
                    "evidence": gate["evidence"],
                    "resolution": "Collect missing values from the original document, reviewer correction or lender confirmation.",
                }
            )
    for item in plan.get("recommended_chain", []):
        if item.get("can_run_now"):
            continue
        blockers.append(
            {
                "id": f"optional-{item.get('dependency_key')}-not-installed",
                "severity": "low",
                "title": f"Optional dependency {item.get('dependency_key')} is not installed",
                "detail": "This does not block the base app; it only prevents that optional adapter from running now.",
                "evidence": [item.get("profile_key")],
                "resolution": "Use the local fallback or install from requirements-ocr-optional.txt after review.",
            }
        )
    return blockers


def build_adapter_readiness_report(plan: dict) -> dict:
    if not isinstance(plan, dict) or plan.get("provider") != "optional-dependency-adapter-plan-v14":
        raise DependencyAdapterError("Expected a V14 optional dependency adapter plan")
    steps = adapter_execution_steps(plan)
    blockers = adapter_blockers(plan)
    high_blockers = [item for item in blockers if item["severity"] == "high"]
    return {
        "provider": "optional-adapter-readiness-report-v14",
        "filename": plan.get("filename"),
        "ready_to_run_base_app": True,
        "ready_to_run_optional_adapter": any(step.get("can_run_now") for step in steps if step.get("dependency_key") != "base_app"),
        "can_prefill_without_manual_review": False,
        "gates": readiness_gates(plan),
        "execution_steps": steps,
        "blockers": blockers,
        "summary": {
            "recommended_profile_count": len(plan.get("recommended_chain", [])),
            "input_contract_count": len(plan.get("input_contracts", [])),
            "blocker_count": len(blockers),
            "high_blocker_count": len(high_blockers),
            "base_fallback_count": len(plan.get("local_fallback_chain", [])),
        },
        "operator_notes": [
            "Use optional OCR adapters only when source files are available, not for already-redacted text alone.",
            "Keep the local mortgage reasoning layer as the source of truth for Canadian terms, rates and penalty caveats.",
            "Run adapter output through the same evidence graph, math audit and lender packet gates before relying on it.",
        ],
    }


def create_adapter_readiness_report(pages: list[Any], *, filename: str = "ocr.txt",
                                    corrections: dict[str, Any] | None = None,
                                    min_confidence: float = 0.0,
                                    question: str | None = None) -> dict:
    plan = create_dependency_adapter_plan(
        pages,
        filename=filename,
        corrections=corrections,
        min_confidence=min_confidence,
        question=question,
    )
    return build_adapter_readiness_report(plan)


def create_dependency_adapter_plan(pages: list[Any], *, filename: str = "ocr.txt",
                                   corrections: dict[str, Any] | None = None,
                                   min_confidence: float = 0.0,
                                   question: str | None = None) -> dict:
    brief = create_contract_brief(
        pages,
        filename=filename,
        corrections=corrections,
        min_confidence=min_confidence,
        question=question,
    )
    return build_dependency_adapter_plan_from_brief(brief)
