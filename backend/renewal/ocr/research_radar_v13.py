"""V13 no-dependency research radar for OCR and contract intelligence.

The goal was to research the web and GitHub twice over while keeping our own
code free of new dependencies. This module records what those
projects are useful for, then converts the research into an in-house adapter
plan that the application can run immediately.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .contract_intelligence import create_contract_brief
from .contract_math_v13 import build_contract_math_audit_from_brief
from .contract_playbook import build_contract_playbook_from_brief


class ResearchRadarError(ValueError):
    """Research radar input was not usable."""


@dataclass(frozen=True)
class ResearchSource:
    key: str
    name: str
    source_type: str
    url: str
    repository: str | None
    latest_signal: str
    useful_for: tuple[str, ...]
    limitations: tuple[str, ...]
    local_strategy: str
    dependency_policy: str
    priority_domains: tuple[str, ...]

    def public(self) -> dict:
        data = asdict(self)
        data["useful_for"] = list(self.useful_for)
        data["limitations"] = list(self.limitations)
        data["priority_domains"] = list(self.priority_domains)
        return data


@dataclass(frozen=True)
class AdapterNeed:
    key: str
    label: str
    weight: int
    reason: str
    evidence: tuple[str, ...]

    def public(self) -> dict:
        data = asdict(self)
        data["evidence"] = list(self.evidence)
        return data


@dataclass(frozen=True)
class AdapterTask:
    id: str
    title: str
    priority: str
    target_module: str
    design_reference: str
    implementation: str
    acceptance_checks: tuple[str, ...]
    no_dependency_reason: str

    def public(self) -> dict:
        data = asdict(self)
        data["acceptance_checks"] = list(self.acceptance_checks)
        return data


def research_sources() -> dict[str, ResearchSource]:
    return {
        "docling": ResearchSource(
            key="docling",
            name="Docling",
            source_type="github_and_web",
            url="https://docling.ai/",
            repository="https://github.com/docling-project/docling",
            latest_signal=(
                "Docling presents itself as open-source document intelligence that converts PDFs, Office files, "
                "HTML, images and audio into structured data with OCR, tables, formulas and reading order."
            ),
            useful_for=(
                "structured document representation",
                "layout-aware table and reading-order concepts",
                "future optional parser adapter",
                "source provenance model",
            ),
            limitations=(
                "large dependency surface compared with this small runnable app",
                "model and OCR behavior varies by installation",
                "not mortgage-specific",
            ),
            local_strategy="Represent OCR output as evidence nodes, sections, clauses, calculations and review tasks.",
            dependency_policy="reference_only_no_runtime_import",
            priority_domains=("layout", "tables", "reading_order", "structured_output"),
        ),
        "unstructured": ResearchSource(
            key="unstructured",
            name="Unstructured",
            source_type="github",
            url="https://docs.unstructured.io/",
            repository="https://github.com/Unstructured-IO/unstructured",
            latest_signal=(
                "GitHub releases continue to ship document partitioning fixes, including recent DOCX, HTML and NLP performance updates."
            ),
            useful_for=(
                "element partitioning vocabulary",
                "preserving lists and tables before downstream reasoning",
                "thinking about text chunks as document elements",
            ),
            limitations=(
                "not bundled here",
                "requires separate installation and parser choices",
                "does not encode Canadian mortgage formulas",
            ),
            local_strategy="Keep local document elements explicit: fields, clauses, sections, questions, checks and graph nodes.",
            dependency_policy="reference_only_no_runtime_import",
            priority_domains=("partitioning", "lists", "tables", "html_docx"),
        ),
        "paddleocr": ResearchSource(
            key="paddleocr",
            name="PaddleOCR",
            source_type="github",
            url="https://github.com/PaddlePaddle/PaddleOCR",
            repository="https://github.com/PaddlePaddle/PaddleOCR",
            latest_signal=(
                "The GitHub project advertises PaddleOCR 3.5.0, PP-OCRv5 and browser inference through PaddleOCR.js."
            ),
            useful_for=(
                "multilingual OCR strategy",
                "browser/local inference direction",
                "structured parsing with PP-Structure style thinking",
            ),
            limitations=(
                "heavy model/runtime footprint",
                "not installed by this package",
                "OCR accuracy still needs field-level review",
            ),
            local_strategy="Use confidence, missing-field gates and review sessions so any OCR engine can be swapped in later.",
            dependency_policy="reference_only_no_runtime_import",
            priority_domains=("ocr", "multilingual", "browser", "structure"),
        ),
        "olmocr": ResearchSource(
            key="olmocr",
            name="olmOCR",
            source_type="github",
            url="https://github.com/allenai/olmocr",
            repository="https://github.com/allenai/olmocr",
            latest_signal=(
                "GitHub releases show ongoing v0.4.x updates in 2026 and the project focuses on linearizing PDFs for LLM datasets/training."
            ),
            useful_for=(
                "unit-test style OCR evaluation mindset",
                "PDF linearization for downstream language tasks",
                "benchmark categories for difficult pages",
            ),
            limitations=(
                "requires its own model/runtime path",
                "not a Canadian mortgage expert",
                "not required for the deterministic fallback",
            ),
            local_strategy="Add deterministic checks that fail loudly when the document evidence is incomplete or inconsistent.",
            dependency_policy="reference_only_no_runtime_import",
            priority_domains=("evaluation", "linearization", "quality_tests", "pdfs"),
        ),
        "marker": ResearchSource(
            key="marker",
            name="Marker",
            source_type="github",
            url="https://github.com/datalab-to/marker",
            repository="https://github.com/datalab-to/marker",
            latest_signal=(
                "Marker converts documents to Markdown, JSON, chunks and HTML, with force-OCR and LLM-assisted paths available."
            ),
            useful_for=(
                "markdown/json conversion model",
                "layout and chunk output formats",
                "force-OCR fallback concept",
            ),
            limitations=(
                "model weights and optional LLM paths are outside this package",
                "license and deployment posture must be reviewed before commercial use",
                "not a replacement for lender-certified values",
            ),
            local_strategy="Return simple JSON packets with stable keys so later Marker/Chandra outputs can map into the same fields.",
            dependency_policy="reference_only_no_runtime_import",
            priority_domains=("markdown", "json", "chunks", "force_ocr"),
        ),
        "surya": ResearchSource(
            key="surya",
            name="Surya",
            source_type="github",
            url="https://github.com/LPAI-Org/Surya",
            repository="https://github.com/LPAI-Org/Surya",
            latest_signal=(
                "The GitHub project describes OCR, layout analysis and line detection across many languages with tunable thresholds."
            ),
            useful_for=(
                "line detection",
                "layout blocks",
                "language-aware OCR",
                "threshold tuning ideas",
            ),
            limitations=(
                "model runtime not bundled",
                "visual bounding boxes are not present in text-only OCR uploads",
                "thresholds require visual debugging",
            ),
            local_strategy="Use text-only fallbacks now and preserve adapter slots for future line/bounding-box evidence.",
            dependency_policy="reference_only_no_runtime_import",
            priority_domains=("line_detection", "layout", "ocr", "languages"),
        ),
        "fcac": ResearchSource(
            key="fcac",
            name="Financial Consumer Agency of Canada mortgage guidance",
            source_type="web_official",
            url="https://www.canada.ca/en/financial-consumer-agency/services/mortgages.html",
            repository=None,
            latest_signal=(
                "FCAC guidance highlights renewal notices, prepayment charge disclosure, IRD factors, rate discounts and posted-rate wording."
            ),
            useful_for=(
                "Canadian mortgage disclosure questions",
                "IRD and three-month-interest caveats",
                "renewal timing and 21-day notice framing",
            ),
            limitations=(
                "not lender-specific payout certification",
                "does not expose each lender's private formula tables",
                "legal interpretation still requires qualified review",
            ),
            local_strategy="Encode lender questions and disclosure prompts while refusing to certify payout amounts.",
            dependency_policy="reference_only_no_runtime_import",
            priority_domains=("canadian_mortgages", "ird", "renewal", "disclosure"),
        ),
    }


def research_source_map() -> dict:
    sources = research_sources()
    return {
        "provider": "contract-research-radar-v13",
        "verified_date": "2026-10-13",
        "source_count": len(sources),
        "runtime_dependency_count": 0,
        "sources": [sources[key].public() for key in sorted(sources)],
        "policy": {
            "imports_external_projects": False,
            "downloads_models": False,
            "stores_raw_ocr": False,
            "reason": "The app uses public projects as design references and keeps its running code self-contained.",
        },
    }


def _graph_summary(brief: dict) -> dict:
    return brief.get("evidence_graph", {}).get("summary", {})


def _risk_ids(brief: dict) -> set[str]:
    return {risk.get("id") for risk in brief.get("risk_assessment", {}).get("risks", [])}


def _field_keys(brief: dict) -> set[str]:
    return set(brief.get("extraction", {}).get("fields", {}))


def infer_adapter_needs(brief: dict, math_audit: dict | None = None) -> list[dict]:
    graph = _graph_summary(brief)
    risks = _risk_ids(brief)
    fields = _field_keys(brief)
    missing = brief.get("readiness", {}).get("missing_required", [])
    needs: list[AdapterNeed] = []

    if missing:
        needs.append(
            AdapterNeed(
                key="required_field_recovery",
                label="Recover required mortgage fields",
                weight=95,
                reason="The contract is blocked because core comparison fields are missing.",
                evidence=tuple(f"field:{key}" for key in missing),
            )
        )
    if graph.get("has_rate_context") or {"contract_rate", "posted_rate", "contract_discount"} & fields:
        needs.append(
            AdapterNeed(
                key="rate_context_reasoning",
                label="Understand posted, contract, discount and offer rates",
                weight=90,
                reason="Canadian mortgage documents often expose multiple rates with different legal meanings.",
                evidence=("field:contract_rate", "field:posted_rate", "field:contract_discount", "field:offered_rate"),
            )
        )
    if graph.get("has_penalty_context") or "ird-language-found" in risks:
        needs.append(
            AdapterNeed(
                key="penalty_language_review",
                label="Review IRD and three-month-interest language",
                weight=88,
                reason="Penalty wording affects whether switching or refinancing makes sense.",
                evidence=("clause:interest_rate_differential", "clause:three_month_interest_penalty"),
            )
        )
    if graph.get("has_timeline_context") or {"maturity_date", "mortgage_start_date", "term_months"} & fields:
        needs.append(
            AdapterNeed(
                key="timeline_validation",
                label="Validate mortgage start date, term and maturity",
                weight=82,
                reason="Dates anchor renewal deadlines, penalty periods and term math.",
                evidence=("field:mortgage_start_date", "field:maturity_date", "field:term_months"),
            )
        )
    if math_audit:
        missing_scenarios = math_audit.get("confidence", {}).get("missing_scenario_ids", [])
        if missing_scenarios:
            needs.append(
                AdapterNeed(
                    key="math_input_completion",
                    label="Collect missing inputs for mortgage math",
                    weight=78,
                    reason="Some formula scenarios could not run with the visible evidence.",
                    evidence=tuple(missing_scenarios),
                )
            )
    if "payment_amount" in fields or "payment_vs_balance_rate_amortization" in str(brief.get("evidence_graph", {})):
        needs.append(
            AdapterNeed(
                key="payment_component_separation",
                label="Separate principal-interest payment from taxes and insurance",
                weight=74,
                reason="Payment comparisons are unreliable when property tax or insurance components are mixed into the payment.",
                evidence=("field:payment_amount", "field:frequency", "clause:property_tax_collection", "clause:insurance_or_protection"),
            )
        )
    if not needs:
        needs.append(
            AdapterNeed(
                key="general_evidence_grounding",
                label="Keep answers grounded to document evidence",
                weight=50,
                reason="No single high-priority adapter need was detected, but OCR output still needs evidence-bound review.",
                evidence=(),
            )
        )
    return [need.public() for need in sorted(needs, key=lambda item: (-item.weight, item.key))]


def _domain_overlap(source: ResearchSource, need: dict) -> int:
    key = str(need.get("key", ""))
    domains = set(source.priority_domains)
    score = 0
    if "field" in key and {"layout", "tables", "partitioning", "ocr"} & domains:
        score += 20
    if "rate" in key and "canadian_mortgages" in domains:
        score += 25
    if "penalty" in key and {"canadian_mortgages", "ird"} & domains:
        score += 30
    if "timeline" in key and {"renewal", "canadian_mortgages"} & domains:
        score += 22
    if "math" in key and {"evaluation", "quality_tests", "canadian_mortgages"} & domains:
        score += 16
    if "payment" in key and {"canadian_mortgages", "tables", "structured_output"} & domains:
        score += 14
    if "evidence" in key and {"structured_output", "evaluation", "partitioning"} & domains:
        score += 12
    return score


def score_sources_for_needs(needs: list[dict]) -> list[dict]:
    scored = []
    for source in research_sources().values():
        total = 0
        matches = []
        for need in needs:
            overlap = _domain_overlap(source, need)
            if overlap:
                total += overlap + int(need.get("weight", 0)) // 10
                matches.append({"need": need["key"], "score": overlap, "reason": need["reason"]})
        if source.dependency_policy == "reference_only_no_runtime_import":
            total += 5
        scored.append(
            {
                "source": source.public(),
                "score": total,
                "matched_needs": matches,
                "recommendation": (
                    "reference_for_local_design"
                    if total > 0
                    else "watch_only"
                ),
            }
        )
    return sorted(scored, key=lambda item: (-item["score"], item["source"]["key"]))


def in_house_adapter_tasks(needs: list[dict]) -> list[dict]:
    tasks: list[AdapterTask] = []
    need_keys = {need["key"] for need in needs}

    if "required_field_recovery" in need_keys:
        tasks.append(
            AdapterTask(
                id="adapter-required-field-recovery",
                title="Improve required-field recovery before comparison prefill",
                priority="critical",
                target_module="backend/renewal/ocr/fields.py",
                design_reference="Docling/Unstructured/PaddleOCR field and element preservation",
                implementation="Keep multiple evidence candidates per required field and require a reviewer choice when candidates conflict.",
                acceptance_checks=(
                    "Thin OCR documents remain blocked.",
                    "Multiple candidate values are exposed with redacted snippets.",
                    "Prefill stays disabled until a reviewer approves the chosen value.",
                ),
                no_dependency_reason="Candidate tracking can run over existing OCR text without importing an external parser.",
            )
        )
    if "rate_context_reasoning" in need_keys:
        tasks.append(
            AdapterTask(
                id="adapter-rate-context",
                title="Strengthen rate context separation",
                priority="high",
                target_module="backend/renewal/ocr/contract_intelligence.py",
                design_reference="FCAC disclosure guidance and contract evidence graph",
                implementation="Separate current, contract, posted, discount and offered rates into evidence nodes with relationship checks.",
                acceptance_checks=(
                    "Contract discount answers cite posted and contract rate evidence.",
                    "Mismatched discount math creates a high-risk item.",
                    "Offer rate is not confused with contract rate.",
                ),
                no_dependency_reason="The needed reasoning is deterministic domain logic, not a model dependency.",
            )
        )
    if "penalty_language_review" in need_keys:
        tasks.append(
            AdapterTask(
                id="adapter-penalty-review",
                title="Add penalty-language math scenarios and lender questions",
                priority="high",
                target_module="backend/renewal/ocr/contract_math_v13.py",
                design_reference="FCAC prepayment charge disclosure and common IRD/three-month-interest comparisons",
                implementation="Estimate visible scenarios, label missing inputs, and request lender-certified payout statements.",
                acceptance_checks=(
                    "Three-month-interest estimate is shown when balance and contract rate exist.",
                    "IRD scenario stays review-only.",
                    "Lender payout statement is always requested.",
                ),
                no_dependency_reason="Penalty estimates are arithmetic over extracted fields, not OCR engine behavior.",
            )
        )
    if "timeline_validation" in need_keys:
        tasks.append(
            AdapterTask(
                id="adapter-timeline-validation",
                title="Validate mortgage date, term and maturity timing",
                priority="high",
                target_module="backend/renewal/ocr/contract_math_v13.py",
                design_reference="Canadian renewal timing and maturity-date disclosure guidance",
                implementation="Calculate months between dates, compare to stated term, and expose renewal-window status.",
                acceptance_checks=(
                    "Start date to maturity produces month count.",
                    "Term mismatches are marked for review.",
                    "21-day renewal timing window is visible.",
                ),
                no_dependency_reason="Date math is fully local and deterministic.",
            )
        )
    if "math_input_completion" in need_keys:
        tasks.append(
            AdapterTask(
                id="adapter-math-input-completion",
                title="Make missing math inputs explicit",
                priority="medium",
                target_module="backend/renewal/ocr/contract_math_v13.py",
                design_reference="olmOCR-style quality checks and testable failure conditions",
                implementation="Return missing scenario IDs and exact fields required before an estimate can run.",
                acceptance_checks=(
                    "Missing input scenarios return status missing_inputs.",
                    "Readiness remains blocked when required math inputs are absent.",
                    "Tests cover complete and thin documents.",
                ),
                no_dependency_reason="Quality checks are structural and can be tested locally.",
            )
        )
    if "payment_component_separation" in need_keys:
        tasks.append(
            AdapterTask(
                id="adapter-payment-components",
                title="Separate payment components before comparison",
                priority="medium",
                target_module="backend/renewal/ocr/document_understanding.py",
                design_reference="table/list preservation from Docling, Unstructured and Marker",
                implementation="Flag payment context that mentions property tax, insurance or protection premiums.",
                acceptance_checks=(
                    "Payment answers warn when tax or insurance clauses are visible.",
                    "Comparison prefill excludes unverified components.",
                    "Reviewer task asks for principal-and-interest-only payment.",
                ),
                no_dependency_reason="Clause detection already works on local OCR text.",
            )
        )
    if not tasks:
        tasks.append(
            AdapterTask(
                id="adapter-general-evidence",
                title="Keep evidence-grounded deterministic fallbacks",
                priority="medium",
                target_module="backend/renewal/ocr/contract_intelligence.py",
                design_reference="Docling structured output and olmOCR quality-check mindset",
                implementation="Continue returning evidence IDs, caveats and manual-review prompts for every answer.",
                acceptance_checks=(
                    "Answers include evidence IDs.",
                    "Raw OCR text is not returned.",
                    "Unknown questions use conservative fallback text.",
                ),
                no_dependency_reason="The existing graph and answer layer are local code.",
            )
        )
    return [task.public() for task in tasks]


def local_capability_inventory() -> dict:
    return {
        "provider": "renewal-radar-local-capabilities-v13",
        "runtime_dependency_count": 0,
        "capabilities": [
            {
                "key": "ocr_text_field_extraction",
                "module": "backend/renewal/ocr/fields.py",
                "status": "implemented",
                "description": "Extracts mortgage fields from OCR text with redacted snippets and confidence gates.",
            },
            {
                "key": "document_understanding",
                "module": "backend/renewal/ocr/document_understanding.py",
                "status": "implemented",
                "description": "Classifies document type, clauses, sections, review prompts and Canadian mortgage terms.",
            },
            {
                "key": "contract_intelligence",
                "module": "backend/renewal/ocr/contract_intelligence.py",
                "status": "implemented",
                "description": "Builds an evidence graph, risk score, lender questions and evidence-grounded answers.",
            },
            {
                "key": "contract_playbook",
                "module": "backend/renewal/ocr/contract_playbook.py",
                "status": "implemented",
                "description": "Turns the brief into reviewer tasks, prefill gates and timelines.",
            },
            {
                "key": "contract_math_audit",
                "module": "backend/renewal/ocr/contract_math_v13.py",
                "status": "implemented",
                "description": "Adds local formula walkthroughs, penalty scenarios and disclosure prompts.",
            },
            {
                "key": "research_radar",
                "module": "backend/renewal/ocr/research_radar_v13.py",
                "status": "implemented",
                "description": "Maps current web/GitHub research to local no-dependency adapter tasks.",
            },
        ],
    }


def concept_summary(needs: list[dict]) -> dict:
    return {
        "headline": "Use the public GitHub ecosystem as a map, not as a runtime dependency.",
        "plain_language": [
            "Modern OCR projects are good at reading layout, tables, lines and document structure.",
            "Canadian mortgage understanding needs additional local rules for rates, discounts, dates, terms, amortization and penalties.",
            "Renewal Radar keeps those mortgage rules in its own code so the app still runs without downloading models or outside packages.",
            "Every answer should cite evidence, explain missing inputs and ask the lender for certified payout details when needed.",
        ],
        "detected_need_keys": [need["key"] for need in needs],
    }


def build_research_radar_from_brief(brief: dict) -> dict:
    if not isinstance(brief, dict) or brief.get("provider") != "deterministic-contract-intelligence-v12":
        raise ResearchRadarError("Expected a V12 contract-intelligence brief")
    playbook = build_contract_playbook_from_brief(brief)
    math_audit = build_contract_math_audit_from_brief(brief)
    needs = infer_adapter_needs(brief, math_audit)
    source_scores = score_sources_for_needs(needs)
    adapter_tasks = in_house_adapter_tasks(needs)
    return {
        "provider": "no-dependency-contract-research-radar-v13",
        "filename": brief.get("filename"),
        "concept": concept_summary(needs),
        "adapter_needs": needs,
        "source_scores": source_scores,
        "in_house_adapter_tasks": adapter_tasks,
        "local_capabilities": local_capability_inventory(),
        "math_audit": math_audit,
        "playbook_summary": {
            "provider": playbook.get("provider"),
            "task_count": playbook.get("checklist", {}).get("task_count"),
            "critical_task_count": playbook.get("checklist", {}).get("critical_task_count"),
            "can_prefill": playbook.get("prefill", {}).get("can_prefill"),
        },
        "dependency_policy": {
            "runtime_external_imports": [],
            "new_pip_dependencies": [],
            "model_downloads": [],
            "github_code_copied": False,
            "statement": "V13 adds local code and tests only; public repositories are cited as research references.",
        },
        "notice": "Research radar is a design and review aid, not a claim that external engines are installed.",
    }


def create_research_radar(pages: list[Any], *, filename: str = "ocr.txt",
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
    return build_research_radar_from_brief(brief)
