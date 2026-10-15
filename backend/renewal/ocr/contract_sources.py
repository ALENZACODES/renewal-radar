"""V12 public-source map for contract-intelligence design.

These entries are not vendored dependencies. They record the public projects and
datasets that shaped the architecture: structure-aware document conversion,
layout-aware parsing, PII boundaries, legal-contract datasets, and legal-domain
language models. The runnable app remains dependency-light and deterministic.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ContractSourceProfile:
    key: str
    name: str
    category: str
    repository: str
    documentation: str
    license_or_access: str
    latest_signal: str
    used_for: tuple[str, ...]
    not_used_for: tuple[str, ...]
    integration_posture: str

    def public(self) -> dict:
        data = asdict(self)
        data["used_for"] = list(data["used_for"])
        data["not_used_for"] = list(data["not_used_for"])
        return data


def contract_source_profiles() -> dict[str, ContractSourceProfile]:
    return {
        "docling": ContractSourceProfile(
            key="docling",
            name="Docling",
            category="document_intelligence",
            repository="https://github.com/docling-project/docling",
            documentation="https://docling-project.github.io/docling/",
            license_or_access="MIT open source",
            latest_signal=(
                "LF AI & Data lists Docling as an open-source document intelligence toolkit; "
                "current docs expose OCR, table-structure, layout and backend-text pipeline options."
            ),
            used_for=(
                "structured document parsing concept",
                "layout/table/reading-order separation",
                "optional V8/V11 OCR adapter posture",
            ),
            not_used_for=(
                "no Docling code is copied",
                "not bundled as a required dependency",
                "not treated as legal advice",
            ),
            integration_posture="optional_adapter_and_architectural_reference",
        ),
        "unstructured": ContractSourceProfile(
            key="unstructured",
            name="Unstructured",
            category="document_partitioning",
            repository="https://github.com/Unstructured-IO/unstructured",
            documentation="https://docs.unstructured.io/",
            license_or_access="open-source package with active GitHub releases",
            latest_signal=(
                "GitHub releases showed 0.27.25 released on October 10, 2026, with recent fixes around "
                "document partitioning and table/list preservation."
            ),
            used_for=(
                "element-style thinking: split documents into fields, clauses, checks and evidence nodes",
                "table/list preservation as a design concern",
                "future adapter candidate for non-image documents",
            ),
            not_used_for=(
                "not bundled",
                "not imported by runtime code",
                "not a source of mortgage-specific rules",
            ),
            integration_posture="future_optional_parser_reference",
        ),
        "presidio": ContractSourceProfile(
            key="presidio",
            name="Microsoft Presidio",
            category="privacy_boundary",
            repository="https://github.com/data-privacy-stack/presidio",
            documentation="https://data-privacy-stack.github.io/presidio/",
            license_or_access="MIT open source",
            latest_signal=(
                "Current Presidio documentation describes analyzer/anonymizer components and broader PII tooling "
                "for text, images, structured data and JSON."
            ),
            used_for=(
                "privacy boundary concept",
                "redaction-before-export mindset",
                "auditable separation between detection and anonymization",
            ),
            not_used_for=(
                "not bundled",
                "not a guarantee that every identifier is removed",
                "not used to send data outside this app",
            ),
            integration_posture="privacy_architecture_reference",
        ),
        "cuad": ContractSourceProfile(
            key="cuad",
            name="Contract Understanding Atticus Dataset",
            category="contract_review_dataset",
            repository="https://github.com/The-Atticus-Project/cuad",
            documentation="https://www.atticusprojectai.org/cuad/",
            license_or_access="public research dataset; review license before commercial model training",
            latest_signal=(
                "The Atticus Project describes CUAD v1 as 510 expert-labeled contracts with 13,000+ labels "
                "covering 41 legal clause categories."
            ),
            used_for=(
                "contract-review framing: clauses, labels, evidence and review questions",
                "inspiration for evidence-grounded answers rather than free-form claims",
                "future benchmark candidate",
            ),
            not_used_for=(
                "not used to train a model in this package",
                "not mortgage-specific",
                "not copied into fixtures",
            ),
            integration_posture="dataset_and_evaluation_reference",
        ),
        "legal_bert": ContractSourceProfile(
            key="legal_bert",
            name="LEGAL-BERT / Contracts-BERT",
            category="legal_language_model",
            repository="https://huggingface.co/nlpaueb/bert-base-uncased-contracts",
            documentation="https://huggingface.co/nlpaueb",
            license_or_access="model-specific licenses; verify before deployment",
            latest_signal=(
                "LEGAL-BERT family includes domain models such as a contracts-pretrained BERT variant; "
                "useful as a future local classifier candidate, not required for V12."
            ),
            used_for=(
                "future optional legal-clause classifier direction",
                "domain-specific model awareness",
                "reason to keep deterministic fallback and evidence IDs",
            ),
            not_used_for=(
                "not bundled",
                "not downloaded",
                "not run in tests",
                "not used to make legal conclusions",
            ),
            integration_posture="future_optional_model_reference",
        ),
        "layoutparser": ContractSourceProfile(
            key="layoutparser",
            name="LayoutParser",
            category="document_layout",
            repository="https://github.com/Layout-Parser/layout-parser",
            documentation="https://layout-parser.github.io/",
            license_or_access="Apache-2.0 open source",
            latest_signal=(
                "GitHub releases list v0.3.4 as the latest patch release; project focuses on document image analysis."
            ),
            used_for=(
                "layout-aware document-image analysis concept",
                "future visual evidence boxes",
                "separation between reading text and locating it",
            ),
            not_used_for=(
                "not bundled",
                "not required to run V12",
                "not used for current mortgage math",
            ),
            integration_posture="future_layout_adapter_reference",
        ),
    }


def contract_source_map() -> dict:
    profiles = contract_source_profiles()
    return {
        "provider": "contract-intelligence-source-map-v12",
        "verified_date": "2026-10-13",
        "source_count": len(profiles),
        "sources": [profiles[key].public() for key in sorted(profiles)],
        "design_principles": [
            "Use structure-aware parsing when available, but keep a deterministic fallback.",
            "Attach every conclusion to evidence IDs and redacted snippets.",
            "Treat contract language as review prompts, not legal conclusions.",
            "Keep privacy and raw-text persistence boundaries explicit.",
            "Use public datasets and legal-domain models as evaluation references before production claims.",
        ],
    }
