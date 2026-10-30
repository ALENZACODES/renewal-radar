"""V15 repeatable benchmark cases for OCR/document adapters.

The optional adapter stack is only useful if it can be tested against mortgage
document details that commonly break OCR: misspelled interest terms, thin
payloads, low confidence lines, table-heavy outputs and candidate conflicts.
This module builds those cases without pulling any external model dependency.
"""
from __future__ import annotations

import copy
import re
from dataclasses import asdict, dataclass
from typing import Any

from .adapter_quality_harness_v15 import evaluate_adapter_payload
from .adapter_reconciliation_v15 import build_reconciliation_report


class AdapterBenchmarkError(ValueError):
    """Adapter benchmark suite input was not usable."""


BASE_MORTGAGE_TEXT = """
Maple Bank Mortgage Renewal Agreement
Mortgage date: 2022-03-01
Outstanding mortgage balance at renewal: $480,000.00
Contract rate: 4.39%
Posted rate: 5.69%
Contract discount: 1.30%
Renewal interest rate: 5.49%
Remaining term: 36 months
Remaining amortization period: 240 months
Maturity date: 2027-03-01
Payment amount: $3,122.52 monthly
Interest rate differential applies if discharged early.
The penalty may be the greater of three months interest or the interest rate differential.
""".strip()


@dataclass(frozen=True)
class BenchmarkExpectation:
    allowed_levels: tuple[str, ...]
    required_quality_flags: tuple[str, ...] = ()
    required_action_ids: tuple[str, ...] = ()
    min_score: int | None = None
    review_required: bool | None = None
    required_reconciliation_statuses: dict[str, str] | None = None

    def public(self) -> dict:
        data = asdict(self)
        data["allowed_levels"] = list(self.allowed_levels)
        data["required_quality_flags"] = list(self.required_quality_flags)
        data["required_action_ids"] = list(self.required_action_ids)
        data["required_reconciliation_statuses"] = self.required_reconciliation_statuses or {}
        return data


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    title: str
    objective: str
    kind: str
    adapter: str
    payload: Any
    expectation: BenchmarkExpectation
    tags: tuple[str, ...] = ()

    def public(self, *, include_payload: bool = False) -> dict:
        data = asdict(self)
        data["expectation"] = self.expectation.public()
        data["tags"] = list(self.tags)
        if not include_payload:
            data.pop("payload", None)
        return data


def marker_payload(text: str = BASE_MORTGAGE_TEXT) -> dict:
    return {
        "provider": "marker",
        "markdown": text,
        "chunks": [
            {"page": 1, "text": "Penalty: interest rate differential and three months interest.", "type": "clause"},
            {"page": 1, "text": "Contract discount is posted rate minus contract rate.", "type": "math_note"},
        ],
        "blocks": [
            {
                "page": 1,
                "type": "table",
                "rows": [
                    ["Balance", "$480,000.00"],
                    ["Contract rate", "4.39%"],
                    ["Posted rate", "5.69%"],
                    ["Offered rate", "5.49%"],
                ],
            }
        ],
    }


def paddle_payload(text: str = BASE_MORTGAGE_TEXT, *, confidence: float = 0.93) -> dict:
    return {
        "provider": "paddleocr",
        "ocr_result": [
            [
                [[0, index * 12], [620, index * 12], [620, index * 12 + 10], [0, index * 12 + 10]],
                [line, confidence],
            ]
            for index, line in enumerate(text.splitlines(), 1)
            if line.strip()
        ],
    }


def docling_payload(text: str = BASE_MORTGAGE_TEXT) -> dict:
    lines = [line for line in text.splitlines() if line.strip()]
    return {
        "provider": "docling",
        "document": {
            "pages": [
                {
                    "page_number": 1,
                    "texts": [
                        {"text": line, "label": "paragraph", "confidence": 0.91}
                        for line in lines
                    ],
                    "tables": [
                        {
                            "caption": "Renewal figures",
                            "rows": [
                                ["Balance", "$480,000.00"],
                                ["Payment", "$3,122.52"],
                                ["Maturity", "2027-03-01"],
                            ],
                            "confidence": 0.89,
                        }
                    ],
                }
            ]
        },
    }


def unstructured_payload(text: str = BASE_MORTGAGE_TEXT) -> list[dict]:
    elements = []
    for index, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        elements.append(
            {
                "type": "Title" if index == 1 else "NarrativeText",
                "text": line,
                "metadata": {"page_number": 1},
                "element_id": f"element-{index:03d}",
                "detection_class_prob": 0.9,
            }
        )
    elements.append(
        {
            "type": "Table",
            "text": "Balance | $480,000.00\nPosted rate | 5.69%\nOffered rate | 5.49%",
            "metadata": {"page_number": 1},
            "element_id": "element-table-001",
            "detection_class_prob": 0.88,
        }
    )
    return elements


def surya_payload(text: str = BASE_MORTGAGE_TEXT, *, confidence: float = 0.9) -> dict:
    return {
        "provider": "surya",
        "pages": [
            {
                "page_number": 1,
                "text_lines": [
                    {
                        "text": line,
                        "confidence": confidence,
                        "bbox": [0, index * 14, 620, index * 14 + 10],
                    }
                    for index, line in enumerate(text.splitlines(), 1)
                    if line.strip()
                ],
                "layout": [
                    {"type": "header", "text": "Mortgage Renewal Agreement", "confidence": 0.94},
                    {"type": "table", "text": "Rates and payment summary", "confidence": 0.86},
                ],
            }
        ],
    }


def olmocr_payload(text: str = BASE_MORTGAGE_TEXT) -> dict:
    return {
        "provider": "olmocr",
        "linearized_text": text,
        "quality_flags": ["linearized mortgage text; verify all numbers against source image"],
    }


NOISE_REPLACEMENTS = (
    ("interest", "intrest"),
    ("Interest", "Intrest"),
    ("differential", "differental"),
    ("mortgage", "morgage"),
    ("Maturity", "Maturlty"),
    ("Outstanding", "Outstandlng"),
)


def apply_ocr_noise(text: str, *, intensity: int = 3) -> str:
    mutated = text
    for before, after in NOISE_REPLACEMENTS[: max(0, min(intensity, len(NOISE_REPLACEMENTS)))]:
        mutated = mutated.replace(before, after)
    return mutated


def remove_lines_containing(text: str, tokens: tuple[str, ...]) -> str:
    lowered = tuple(token.lower() for token in tokens)
    kept = []
    for line in text.splitlines():
        if any(token in line.lower() for token in lowered):
            continue
        kept.append(line)
    return "\n".join(kept)


def replace_line_value(text: str, prefix: str, replacement: str) -> str:
    lines = []
    pattern = re.compile(rf"^\s*{re.escape(prefix)}\s*:.*$", flags=re.I)
    for line in text.splitlines():
        lines.append(f"{prefix}: {replacement}" if pattern.match(line) else line)
    return "\n".join(lines)


def thin_rate_text() -> str:
    return "Contract rate: 4.39%\nPosted rate: 5.69%\nContract discount: 1.30%"


def _single_case(id_: str, title: str, adapter: str, payload: Any,
                 expectation: BenchmarkExpectation, *tags: str,
                 objective: str = "Evaluate one adapter-shaped payload.") -> BenchmarkCase:
    return BenchmarkCase(
        id=id_,
        title=title,
        objective=objective,
        kind="single_payload",
        adapter=adapter,
        payload=payload,
        expectation=expectation,
        tags=tuple(tags),
    )


def _candidate_case(id_: str, title: str, candidates: list[dict[str, Any]],
                    expectation: BenchmarkExpectation, *tags: str) -> BenchmarkCase:
    return BenchmarkCase(
        id=id_,
        title=title,
        objective="Compare and reconcile multiple adapter candidates for the same document.",
        kind="candidate_set",
        adapter="multi",
        payload={"candidates": candidates},
        expectation=expectation,
        tags=tuple(tags),
    )


def build_default_benchmark_cases(
    adapters: list[str] | None = None,
    *,
    include_candidate_sets: bool = True,
) -> list[BenchmarkCase]:
    allowed = {adapter.lower() for adapter in adapters or []}

    def include(adapter: str) -> bool:
        return not allowed or adapter in allowed

    reviewable = BenchmarkExpectation(
        allowed_levels=("reviewable", "needs_review"),
        required_quality_flags=("has_money", "has_rate", "has_date", "has_penalty_language"),
        min_score=60,
    )
    blocked_missing_balance = BenchmarkExpectation(
        allowed_levels=("blocked",),
        required_quality_flags=("has_rate",),
        required_action_ids=("action-field-balance",),
        review_required=True,
    )
    low_confidence = BenchmarkExpectation(
        allowed_levels=("reviewable", "needs_review", "blocked"),
        required_quality_flags=("has_money", "has_rate"),
        required_action_ids=("action-review-low-confidence",),
        review_required=True,
    )

    cases: list[BenchmarkCase] = []
    if include("marker"):
        cases.append(_single_case(
            "marker-complete-renewal",
            "Marker-style complete renewal markdown",
            "marker",
            marker_payload(),
            reviewable,
            "markdown",
            "tables",
            "complete",
        ))
        cases.append(_single_case(
            "marker-thin-rates-only",
            "Marker-style thin rate excerpt",
            "marker",
            marker_payload(thin_rate_text()),
            blocked_missing_balance,
            "thin",
            "missing-balance",
        ))
    if include("paddleocr"):
        cases.append(_single_case(
            "paddleocr-complete-lines",
            "PaddleOCR-style complete line output",
            "paddleocr",
            paddle_payload(),
            reviewable,
            "line-ocr",
            "complete",
        ))
        cases.append(_single_case(
            "paddleocr-low-confidence-lines",
            "PaddleOCR-style low confidence output",
            "paddleocr",
            paddle_payload(confidence=0.41),
            low_confidence,
            "line-ocr",
            "low-confidence",
        ))
    if include("docling"):
        cases.append(_single_case(
            "docling-structured-page",
            "Docling-style structured page with table",
            "docling",
            docling_payload(),
            reviewable,
            "layout",
            "tables",
            "complete",
        ))
    if include("unstructured"):
        cases.append(_single_case(
            "unstructured-elements",
            "Unstructured-style document elements",
            "unstructured",
            unstructured_payload(),
            reviewable,
            "elements",
            "complete",
        ))
    if include("surya"):
        cases.append(_single_case(
            "surya-noisy-lines",
            "Surya-style OCR lines with mortgage spelling noise",
            "surya",
            surya_payload(apply_ocr_noise(BASE_MORTGAGE_TEXT, intensity=4)),
            BenchmarkExpectation(
                allowed_levels=("reviewable", "needs_review", "blocked"),
                required_quality_flags=("has_money", "has_rate", "has_date"),
                min_score=35,
            ),
            "noise",
            "layout",
        ))
    if include("olmocr"):
        cases.append(_single_case(
            "olmocr-linearized-text",
            "olmOCR-style linearized text",
            "olmocr",
            olmocr_payload(),
            reviewable,
            "linearized",
            "complete",
        ))

    if include_candidate_sets and (not allowed or {"marker", "paddleocr"} & allowed):
        cases.append(_candidate_case(
            "multi-consensus-marker-paddle",
            "Marker and PaddleOCR agree on renewal fields",
            [
                {"adapter": "marker", "payload": marker_payload()},
                {"adapter": "paddleocr", "payload": paddle_payload()},
            ],
            BenchmarkExpectation(
                allowed_levels=("reviewable", "needs_review", "blocked"),
                required_reconciliation_statuses={"contract_rate": "consensus"},
            ),
            "multi-adapter",
            "reconciliation",
        ))
        conflict_text = replace_line_value(BASE_MORTGAGE_TEXT, "Posted rate", "5.19%")
        cases.append(_candidate_case(
            "multi-conflict-posted-rate",
            "Adapter candidates disagree on posted rate",
            [
                {"adapter": "marker", "payload": marker_payload()},
                {"adapter": "paddleocr", "payload": paddle_payload(conflict_text)},
            ],
            BenchmarkExpectation(
                allowed_levels=("reviewable", "needs_review", "blocked"),
                required_reconciliation_statuses={"posted_rate": "conflict"},
            ),
            "multi-adapter",
            "conflict",
            "posted-rate",
        ))
    return cases


def _level_allowed(level: str, allowed_levels: tuple[str, ...]) -> bool:
    return level in set(allowed_levels)


def _required_flags_present(quality: dict, flags: tuple[str, ...]) -> tuple[bool, list[str]]:
    missing = [flag for flag in flags if not quality.get(flag)]
    return not missing, missing


def _required_actions_present(actions: list[dict], ids: tuple[str, ...]) -> tuple[bool, list[str]]:
    present = {str(action.get("id")) for action in actions}
    missing = [id_ for id_ in ids if id_ not in present]
    return not missing, missing


def _reconciliation_statuses(report: dict) -> dict[str, str]:
    fields = report.get("reconciliation", {}).get("fields", [])
    return {str(field.get("field")): str(field.get("status")) for field in fields}


def _expectation_checks(expectation: BenchmarkExpectation, *,
                        level: str, score: int, quality: dict,
                        actions: list[dict], review_required: bool | None,
                        reconciliation_statuses: dict[str, str] | None = None) -> tuple[bool, list[dict]]:
    checks = []
    level_ok = _level_allowed(level, expectation.allowed_levels)
    checks.append({
        "id": "level",
        "passed": level_ok,
        "detail": f"Level {level!r} in allowed set {', '.join(expectation.allowed_levels)}.",
    })
    if expectation.min_score is not None:
        checks.append({
            "id": "min-score",
            "passed": score >= expectation.min_score,
            "detail": f"Score {score} >= {expectation.min_score}.",
        })
    flags_ok, missing_flags = _required_flags_present(quality, expectation.required_quality_flags)
    if expectation.required_quality_flags:
        checks.append({
            "id": "quality-flags",
            "passed": flags_ok,
            "detail": "Missing: " + ", ".join(missing_flags) if missing_flags else "Required quality flags present.",
        })
    actions_ok, missing_actions = _required_actions_present(actions, expectation.required_action_ids)
    if expectation.required_action_ids:
        checks.append({
            "id": "actions",
            "passed": actions_ok,
            "detail": "Missing: " + ", ".join(missing_actions) if missing_actions else "Required actions present.",
        })
    if expectation.review_required is not None and review_required is not None:
        checks.append({
            "id": "review-required",
            "passed": review_required is expectation.review_required,
            "detail": f"Review required is {review_required}.",
        })
    if expectation.required_reconciliation_statuses:
        statuses = reconciliation_statuses or {}
        for field, expected_status in expectation.required_reconciliation_statuses.items():
            actual = statuses.get(field)
            checks.append({
                "id": f"reconciliation-{field}",
                "passed": actual == expected_status,
                "detail": f"{field} status {actual!r}; expected {expected_status!r}.",
            })
    return all(check["passed"] for check in checks), checks


def evaluate_benchmark_case(case: BenchmarkCase) -> dict:
    if case.kind == "single_payload":
        packet = evaluate_adapter_payload(copy.deepcopy(case.payload), case.adapter)
        score = packet.get("evaluation", {}).get("score", {})
        actions = packet.get("evaluation", {}).get("next_actions", [])
        level = str(score.get("level") or "unknown")
        numeric_score = int(score.get("score") or 0)
        quality = packet.get("quality", {})
        review_required = bool(quality.get("review_required"))
        passed, checks = _expectation_checks(
            case.expectation,
            level=level,
            score=numeric_score,
            quality=quality,
            actions=actions,
            review_required=review_required,
        )
        return {
            "provider": "adapter-benchmark-case-result-v15",
            "case": case.public(),
            "status": "pass" if passed else "fail",
            "level": level,
            "score": numeric_score,
            "quality": quality,
            "action_ids": [action.get("id") for action in actions],
            "checks": checks,
        }
    if case.kind == "candidate_set":
        candidates = case.payload.get("candidates") if isinstance(case.payload, dict) else None
        if not isinstance(candidates, list):
            raise AdapterBenchmarkError(f"Benchmark case {case.id} has no candidate list")
        report = build_reconciliation_report(copy.deepcopy(candidates))
        scores = report.get("workbench", {}).get("scores", [])
        top = scores[0] if scores else {}
        level = str(top.get("level") or "unknown")
        numeric_score = int(top.get("score") or 0)
        statuses = _reconciliation_statuses(report)
        passed, checks = _expectation_checks(
            case.expectation,
            level=level,
            score=numeric_score,
            quality=report.get("workbench", {}).get("selected_quality", {}),
            actions=report.get("workbench", {}).get("selected_next_actions", []),
            review_required=bool(report.get("reconciliation", {}).get("review_required")),
            reconciliation_statuses=statuses,
        )
        return {
            "provider": "adapter-benchmark-case-result-v15",
            "case": case.public(),
            "status": "pass" if passed else "fail",
            "level": level,
            "score": numeric_score,
            "reconciliation_statuses": statuses,
            "workbench": {
                "evaluated_count": report.get("workbench", {}).get("evaluated_count"),
                "selected_candidate_id": report.get("workbench", {}).get("selected_candidate_id"),
                "error_count": report.get("workbench", {}).get("error_count"),
            },
            "checks": checks,
        }
    raise AdapterBenchmarkError(f"Unsupported benchmark case kind: {case.kind}")


def summarize_benchmark_results(results: list[dict]) -> dict:
    total = len(results)
    passed = sum(1 for result in results if result.get("status") == "pass")
    failed = total - passed
    scores = [int(result.get("score") or 0) for result in results]
    levels: dict[str, int] = {}
    adapters: dict[str, int] = {}
    tags: dict[str, int] = {}
    for result in results:
        level = str(result.get("level") or "unknown")
        levels[level] = levels.get(level, 0) + 1
        case = result.get("case", {})
        adapter = str(case.get("adapter") or "unknown")
        adapters[adapter] = adapters.get(adapter, 0) + 1
        for tag in case.get("tags", []):
            tags[tag] = tags.get(tag, 0) + 1
    return {
        "provider": "adapter-benchmark-summary-v15",
        "case_count": total,
        "passed_count": passed,
        "failed_count": failed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "average_score": round(sum(scores) / total, 2) if total else 0.0,
        "levels": levels,
        "adapter_coverage": adapters,
        "tag_coverage": tags,
        "ready": failed == 0 and total > 0,
    }


def recommended_benchmark_actions(results: list[dict]) -> list[dict]:
    actions = []
    for result in results:
        if result.get("status") == "pass":
            continue
        failed_checks = [check for check in result.get("checks", []) if not check.get("passed")]
        actions.append(
            {
                "id": f"benchmark-action-{result.get('case', {}).get('id')}",
                "priority": "high",
                "title": f"Investigate benchmark case: {result.get('case', {}).get('title')}",
                "detail": "; ".join(check.get("detail", "") for check in failed_checks[:3]),
                "case_id": result.get("case", {}).get("id"),
            }
        )
    if not actions:
        actions.append(
            {
                "id": "benchmark-action-keep-fixtures",
                "priority": "low",
                "title": "Keep benchmark fixtures in release checks",
                "detail": "All benchmark cases behaved as expected; keep running them with adapter changes.",
                "case_id": None,
            }
        )
    return actions


def run_adapter_benchmark_suite(
    adapters: list[str] | None = None,
    *,
    include_candidate_sets: bool = True,
) -> dict:
    cases = build_default_benchmark_cases(adapters, include_candidate_sets=include_candidate_sets)
    if not cases:
        raise AdapterBenchmarkError("No benchmark cases matched the requested adapters")
    results = [evaluate_benchmark_case(case) for case in cases]
    summary = summarize_benchmark_results(results)
    return {
        "provider": "adapter-benchmark-suite-v15",
        "summary": summary,
        "results": results,
        "actions": recommended_benchmark_actions(results),
        "notice": "Benchmarks use synthetic mortgage text and adapter-shaped payloads; they validate pipeline behavior, not model accuracy.",
    }
