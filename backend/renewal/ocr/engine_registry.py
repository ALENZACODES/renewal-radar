"""V11 OCR engine readiness registry.

The application does not vendor OCR projects from GitHub. Instead it keeps a
small, auditable registry of supported integration targets and uses that
registry to explain which engine family should be selected for a given mortgage
document workflow. The registry is intentionally data-driven so future releases
can update source URLs, installation notes, or scoring weights without changing
the V8 camera pipeline or V10 field extractor.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


class OCREngineRegistryError(ValueError):
    """The OCR engine-planning request is malformed."""


@dataclass(frozen=True)
class OCREngineProfile:
    key: str
    name: str
    repository: str
    documentation: str
    license_name: str
    latest_signal: str
    install_hint: str
    runtime: str
    privacy_posture: str
    setup_weight: str
    strengths: tuple[str, ...]
    limitations: tuple[str, ...]
    best_for: tuple[str, ...]
    supported_inputs: tuple[str, ...]
    output_shapes: tuple[str, ...]
    language_notes: str
    production_notes: tuple[str, ...]
    local_default: bool = False
    supports_layout: bool = False
    supports_tables: bool = False
    supports_browser: bool = False
    requires_gpu_for_best_results: bool = False

    def public(self) -> dict:
        data = asdict(self)
        for key in (
            "strengths",
            "limitations",
            "best_for",
            "supported_inputs",
            "output_shapes",
            "production_notes",
        ):
            data[key] = list(data[key])
        return data


def engine_profiles() -> dict[str, OCREngineProfile]:
    return {
        "auto": OCREngineProfile(
            key="auto",
            name="Auto OCR router",
            repository="local-adapter",
            documentation="local-adapter",
            license_name="Project MIT",
            latest_signal="Tries installed modern OCR adapters first, then falls back to a warning-only page when no runtime is available.",
            install_hint="No setup required; install PaddleOCR, Docling, EasyOCR, RapidOCR or Tesseract to improve results.",
            runtime="adapter_router",
            privacy_posture="local_process",
            setup_weight="low",
            strengths=(
                "Does not hard-fail just because an optional OCR runtime is missing.",
                "Prefers modern installed engines while preserving a controlled fallback.",
                "Keeps V10/V11 review workflows alive so missing fields become review tasks.",
            ),
            limitations=(
                "An empty warning-only OCR result is not a successful read.",
                "Best results still require installing and validating a real OCR engine.",
                "Adapter order should be tuned for production hardware and document type.",
            ),
            best_for=(
                "resilient_demo_ingestion",
                "mixed_deployment_environments",
                "no_setup_fallback",
            ),
            supported_inputs=("image",),
            output_shapes=("text", "warnings"),
            language_notes="Passes the selected English/French language to downstream local engines where supported.",
            production_notes=(
                "Use explicit engine selection for regulated production workflows.",
                "Alert when auto falls through to no_ocr_runtime_available.",
            ),
            local_default=True,
        ),
        "tesseract": OCREngineProfile(
            key="tesseract",
            name="Tesseract OCR",
            repository="https://github.com/tesseract-ocr/tesseract",
            documentation="https://tesseract-ocr.github.io/tessdoc/",
            license_name="Apache-2.0",
            latest_signal="Tesseract 5 is the current stable major version; release notes list 5.5.3 on July 24, 2026.",
            install_hint="Install the platform Tesseract binary and language data; use the existing V8 tesseract CLI adapter.",
            runtime="native_binary",
            privacy_posture="local_process",
            setup_weight="low",
            strengths=(
                "Mature local OCR with no cloud dependency.",
                "Useful for clear mortgage renewal letters and scanned text pages.",
                "Supports plain text, TSV, hOCR, ALTO, PAGE and searchable PDF outputs.",
                "Wide language-data ecosystem and predictable deployment story.",
            ),
            limitations=(
                "Image quality and preprocessing matter a lot.",
                "Not a full document-layout or table-understanding pipeline by itself.",
                "Complex photographed documents may need recapture or a richer parser.",
            ),
            best_for=(
                "privacy_first_local_ocr",
                "simple_text_extraction",
                "production_default_when_native_binary_is_available",
            ),
            supported_inputs=("png", "jpeg", "tiff", "webp_via_preprocessing"),
            output_shapes=("text", "tsv", "hocr", "alto", "page_xml", "searchable_pdf"),
            language_notes="Tesseract has UTF-8 support and published traineddata for many languages; language codes are engine-native, e.g. eng or fra.",
            production_notes=(
                "Pin the server binary version and language packs.",
                "Record tesseract --version in operational diagnostics.",
                "Use the V10 manual-review layer for every extracted financial field.",
            ),
            local_default=True,
        ),
        "docling": OCREngineProfile(
            key="docling",
            name="Docling",
            repository="https://github.com/docling-project/docling",
            documentation="https://github.com/docling-project/docling/blob/main/docs/concepts/OCR.md",
            license_name="MIT",
            latest_signal="The main branch OCR docs list RapidOCR, Nemotron-OCR, EasyOCR, ocrmac, tesseract-CLI and tesserocr engine options.",
            install_hint="Install Docling separately with the chosen OCR extras; keep heavy models outside this ZIP.",
            runtime="python_pipeline",
            privacy_posture="local_or_configured_remote",
            setup_weight="medium",
            strengths=(
                "Document conversion pipeline with layout, reading order and table options.",
                "Can select OCR engines through a common OcrOptions interface.",
                "Useful when a PDF has mixed vector text, scanned regions and tables.",
            ),
            limitations=(
                "Heavier dependency surface than a CLI-only Tesseract deployment.",
                "Some OCR engines require model downloads, platform-specific libraries or GPU-friendly hardware.",
                "Remote serving modes require separate privacy and network review.",
            ),
            best_for=(
                "layout_aware_pdf_conversion",
                "mixed_programmatic_and_scanned_pdf",
                "future_table_extraction_path",
            ),
            supported_inputs=("pdf", "image", "docx", "pptx", "html", "office_documents"),
            output_shapes=("markdown", "json", "docling_document", "text"),
            language_notes="Docling accepts engine-native language codes and canonical BCP-47 tags prefixed with iso: for supported OCR engines.",
            production_notes=(
                "Choose the OCR engine explicitly instead of relying on a hidden default.",
                "Disable OCR for programmatic PDF text when the source already has extractable text.",
                "Keep model cache, runtime versions and remote endpoints out of borrower exports.",
            ),
            supports_layout=True,
            supports_tables=True,
        ),
        "paddleocr": OCREngineProfile(
            key="paddleocr",
            name="PaddleOCR",
            repository="https://github.com/PaddlePaddle/PaddleOCR",
            documentation="https://paddleocr.dev/doc",
            license_name="Apache-2.0",
            latest_signal="Current public docs describe PaddleOCR 3.7.0, PP-OCRv6, PP-StructureV3, PaddleOCR-VL and PaddleOCR.js.",
            install_hint="Install PaddlePaddle first, then paddleocr extras appropriate for CPU/GPU; do not bundle model weights in this project ZIP.",
            runtime="python_or_browser_pipeline",
            privacy_posture="local_process_or_browser",
            setup_weight="high",
            strengths=(
                "Strong modern OCR and document parsing family.",
                "PP-StructureV3 and PaddleOCR-VL target layout, tables, formulas and reading order.",
                "Browser inference path is relevant for future client-side privacy experiments.",
                "Good candidate for photographed or warped mortgage documents after proof-of-concept validation.",
            ),
            limitations=(
                "Large dependency and model footprint compared with Tesseract.",
                "Best document-parsing accuracy may require GPU or a dedicated inference server.",
                "APIs changed across major versions, so adapters must pin and test exact versions.",
            ),
            best_for=(
                "high_accuracy_document_parsing",
                "table_or_layout_heavy_sources",
                "future_browser_or_gpu_ocr",
            ),
            supported_inputs=("image", "pdf", "office_documents_via_pipelines"),
            output_shapes=("text_lines", "boxes", "markdown", "json", "structured_document"),
            language_notes="Recent PP-OCR releases advertise broad multilingual coverage; confirm exact model/language support before production use.",
            production_notes=(
                "Pin PaddlePaddle and PaddleOCR versions together.",
                "Run a mortgage-document benchmark before enabling as a default.",
                "Treat VLM output as extracted evidence requiring V10/V11 review gates.",
            ),
            supports_layout=True,
            supports_tables=True,
            supports_browser=True,
            requires_gpu_for_best_results=True,
        ),
        "easyocr": OCREngineProfile(
            key="easyocr",
            name="EasyOCR",
            repository="https://github.com/JaidedAI/EasyOCR",
            documentation="https://github.com/JaidedAI/EasyOCR",
            license_name="Apache-2.0",
            latest_signal="A stable open-source OCR option often surfaced through direct use or Docling engine selection.",
            install_hint="Install EasyOCR separately when its model footprint and PyTorch dependency are acceptable.",
            runtime="python_model",
            privacy_posture="local_process",
            setup_weight="medium",
            strengths=(
                "Simple Python API and many-language OCR support.",
                "Can be a fallback where Tesseract language data or segmentation performs poorly.",
                "Integrates with Docling as one selectable OCR backend.",
            ),
            limitations=(
                "Requires model files and PyTorch dependency management.",
                "Not a mortgage-specific extraction system by itself.",
                "Less attractive than Tesseract for tiny server deployments.",
            ),
            best_for=(
                "model_based_fallback_ocr",
                "non_tesseract_language_or_segmentation_trials",
            ),
            supported_inputs=("image",),
            output_shapes=("text", "boxes", "confidence"),
            language_notes="Language list depends on EasyOCR model support and installed weights.",
            production_notes=(
                "Cache model weights in managed infrastructure, not inside exported source ZIPs.",
                "Benchmark against Tesseract and PaddleOCR on mortgage renewals before defaulting.",
            ),
        ),
        "rapidocr": OCREngineProfile(
            key="rapidocr",
            name="RapidOCR",
            repository="https://github.com/RapidAI/RapidOCR",
            documentation="https://github.com/RapidAI/RapidOCR",
            license_name="Apache-2.0",
            latest_signal="Docling's current OCR docs include RapidOCR and PP-OCR language mapping options.",
            install_hint="Install through Docling/RapidOCR extras when ONNX-style local inference is preferred.",
            runtime="python_onnx_pipeline",
            privacy_posture="local_process",
            setup_weight="medium",
            strengths=(
                "Local model-based OCR path with deployment options around ONNX runtimes.",
                "Useful as a Docling-backed OCR engine for layout-aware conversions.",
                "Can provide a middle ground between Tesseract simplicity and heavier PaddleOCR stacks.",
            ),
            limitations=(
                "Model and runtime compatibility need environment-specific validation.",
                "Current application has no direct RapidOCR adapter yet.",
                "Mortgage-field correctness still depends on V10/V11 review.",
            ),
            best_for=(
                "docling_local_ocr_backend",
                "onnx_runtime_experiments",
            ),
            supported_inputs=("image", "pdf_via_docling"),
            output_shapes=("text", "boxes", "confidence"),
            language_notes="Docling maps iso: language tags to RapidOCR/PP-OCR notation where supported.",
            production_notes=(
                "Keep direct adapter work separate from the current V8 Tesseract path.",
                "Validate model-size and language compatibility at startup.",
            ),
            supports_layout=True,
        ),
    }


def list_engine_profiles() -> dict:
    profiles = engine_profiles()
    return {
        "provider": "renewal-radar-ocr-engine-registry-v11",
        "engine_count": len(profiles),
        "engines": [profile.public() for profile in profiles.values()],
        "notice": "Registry entries describe integration posture; model packages are not bundled.",
    }


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _choice(value: Any, allowed: set[str], default: str, name: str) -> str:
    text = str(value or default).strip().lower()
    if text not in allowed:
        raise OCREngineRegistryError(f"{name} must be one of: {', '.join(sorted(allowed))}")
    return text


def normalize_engine_request(request: dict | None) -> dict:
    request = dict(request or {})
    document_type = _choice(
        request.get("document_type"),
        {"image", "pdf", "mixed_pdf", "office", "unknown"},
        "unknown",
        "document_type",
    )
    privacy_mode = _choice(
        request.get("privacy_mode"),
        {"local_only", "local_or_remote"},
        "local_only",
        "privacy_mode",
    )
    setup_budget = _choice(
        request.get("setup_budget"),
        {"low", "medium", "high"},
        "low",
        "setup_budget",
    )
    output_goal = _choice(
        request.get("output_goal"),
        {"plain_text", "fields", "layout", "tables", "markdown_json"},
        "fields",
        "output_goal",
    )
    languages = request.get("languages") or ["eng"]
    if not isinstance(languages, list) or len(languages) > 12:
        raise OCREngineRegistryError("languages must be a list of at most 12 entries")
    clean_languages = []
    for item in languages:
        text = str(item or "").strip()
        if not text or len(text) > 32:
            raise OCREngineRegistryError("Each language entry must be 1-32 characters")
        clean_languages.append(text)
    return {
        "document_type": document_type,
        "privacy_mode": privacy_mode,
        "setup_budget": setup_budget,
        "output_goal": output_goal,
        "needs_layout": _bool(request.get("needs_layout", output_goal in {"layout", "markdown_json"})),
        "needs_tables": _bool(request.get("needs_tables", output_goal == "tables")),
        "photographed_document": _bool(request.get("photographed_document", False)),
        "allow_gpu": _bool(request.get("allow_gpu", False)),
        "languages": clean_languages,
    }


def _setup_score(profile: OCREngineProfile, budget: str) -> tuple[int, list[str]]:
    order = {"low": 0, "medium": 1, "high": 2}
    required = order[profile.setup_weight]
    available = order[budget]
    if required <= available:
        return 10 - required * 2, []
    return -12, [f"setup_budget_below_{profile.setup_weight}"]


def _privacy_score(profile: OCREngineProfile, mode: str) -> tuple[int, list[str]]:
    if mode == "local_only" and profile.privacy_posture == "local_or_configured_remote":
        return 4, ["configure_docling_for_local_engine_only"]
    if mode == "local_only" and "local" not in profile.privacy_posture:
        return -20, ["not_local_only"]
    return 8, []


def _document_score(profile: OCREngineProfile, request: dict) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    doc_type = request["document_type"]
    supported = set(profile.supported_inputs)
    if doc_type == "image" and {"image", "png", "jpeg", "tiff"} & supported:
        score += 8
    elif doc_type == "pdf" and ("pdf" in supported or "pdf_via_docling" in supported):
        score += 8
    elif doc_type == "mixed_pdf" and profile.supports_layout:
        score += 10
    elif doc_type == "office" and any("office" in item for item in supported):
        score += 8
    elif doc_type == "unknown":
        score += 2
    else:
        score -= 8
        reasons.append("input_type_not_primary_fit")
    if request["needs_layout"]:
        if profile.supports_layout:
            score += 10
        else:
            score -= 8
            reasons.append("layout_needed_but_engine_is_text_first")
    if request["needs_tables"]:
        if profile.supports_tables:
            score += 10
        else:
            score -= 8
            reasons.append("table_structure_needed_but_not_native")
    if request["photographed_document"] and profile.key in {"paddleocr", "docling", "easyocr"}:
        score += 5
    if request["photographed_document"] and profile.key == "tesseract":
        score -= 2
        reasons.append("photographed_documents_need_strong_preprocessing")
    if profile.requires_gpu_for_best_results and not request["allow_gpu"]:
        score -= 4
        reasons.append("best_results_prefer_gpu_or_dedicated_server")
    return score, reasons


def score_engine(profile: OCREngineProfile, request: dict) -> dict:
    setup_score, setup_notes = _setup_score(profile, request["setup_budget"])
    privacy_score, privacy_notes = _privacy_score(profile, request["privacy_mode"])
    doc_score, doc_notes = _document_score(profile, request)
    score = setup_score + privacy_score + doc_score
    if profile.local_default and request["setup_budget"] == "low" and not request["needs_layout"]:
        score += 6
    if request["output_goal"] == "fields" and profile.key == "tesseract":
        score += 3
    if request["output_goal"] in {"layout", "tables", "markdown_json"} and profile.key == "docling":
        score += 4
    if request["output_goal"] in {"layout", "tables", "markdown_json"} and profile.key == "paddleocr":
        score += 3
    notes = setup_notes + privacy_notes + doc_notes
    return {
        "engine": profile.key,
        "name": profile.name,
        "score": score,
        "recommended": score >= 12,
        "notes": notes,
        "install_hint": profile.install_hint,
        "latest_signal": profile.latest_signal,
        "repository": profile.repository,
        "documentation": profile.documentation,
        "runtime": profile.runtime,
        "privacy_posture": profile.privacy_posture,
    }


def recommend_ocr_engines(request: dict | None = None) -> dict:
    normalized = normalize_engine_request(request)
    scored = [
        score_engine(profile, normalized)
        for profile in engine_profiles().values()
    ]
    scored.sort(key=lambda item: (-item["score"], item["engine"]))
    primary = scored[0]
    fallback = next((item for item in scored[1:] if item["score"] >= 8), scored[1])
    return {
        "provider": "renewal-radar-ocr-engine-registry-v11",
        "request": normalized,
        "primary": primary,
        "fallback": fallback,
        "ranked": scored,
        "implementation_note": (
            "The current runnable app keeps Tesseract/Docling adapters optional. "
            "Selections here are integration guidance, not proof that a binary or model is installed."
        ),
        "field_review_required": True,
    }
